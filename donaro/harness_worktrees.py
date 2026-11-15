"""실제 임시 Git 저장소로 worktree 격리·검증·충돌·원본 인덱스 보존을 검사한다."""
from pathlib import Path
import json
import subprocess
import tempfile
import task_worktrees as w
from task_workers import WorktreePatchWorker


def git(root,*args):
    p=subprocess.run(['git',*args],cwd=root,capture_output=True,text=True,encoding='utf-8')
    assert p.returncode==0,p.stderr
    return p.stdout.strip()


def check():
    with tempfile.TemporaryDirectory() as d:
        root=Path(d);repo=root/'repo';repo.mkdir();container=root/'tasks'
        git(repo,'init');git(repo,'config','user.name','test');git(repo,'config','user.email','test@example.invalid')
        (repo/'a.py').write_text('def value():\n    return 1\n',encoding='utf-8')
        (repo/'harness_test.py').write_text('from a import value\nassert value() == 2\n',encoding='utf-8')
        (repo/'untouched.py').write_text('x=1\n',encoding='utf-8');git(repo,'add','.');git(repo,'commit','-m','base')
        (repo/'a.py').write_text('def value():\n    return 1\n# user WIP\n',encoding='utf-8')
        (repo/'untouched.py').write_text('x=2\n',encoding='utf-8');git(repo,'add','untouched.py')
        head=git(repo,'rev-parse','HEAD');index=git(repo,'diff','--cached');original=(repo/'a.py').read_bytes()
        spec={'repository':str(repo),'paths':['a.py','harness_test.py'],'checks':[['python','harness_test.py']]}
        a=w.prepare(1,spec,root,container);b=w.prepare(2,spec,root,container)
        assert Path(a['path']).joinpath('a.py').read_bytes()==original
        for state in (a,b):
            Path(state['path']).joinpath('a.py').write_text('def value():\n    return 2\n# user WIP\n',encoding='utf-8');w.verify(state)
        assert (repo/'a.py').read_bytes()==original
        w.integrate(a);assert 'return 2' in (repo/'a.py').read_text()
        assert git(repo,'rev-parse','HEAD')==head and git(repo,'diff','--cached')==index
        try:w.integrate(b);raise AssertionError('conflict overwritten')
        except ValueError as e:assert '충돌' in str(e)
        assert Path(b['path']).is_dir() and w.prepare(2,spec,root,container)['branch']==b['branch']
        # 실패한 검증과 범위 밖 수정은 원본을 건드리지 않는다.
        c=w.prepare(3,spec,root,container);Path(c['path']).joinpath('a.py').write_text('def value():\n    return 9\n')
        try:w.verify(c);raise AssertionError('failed checks accepted')
        except ValueError as e:assert '검증 실패' in str(e)
        e=w.prepare(4,spec,root,container);Path(e['path']).joinpath('untouched.py').write_text('x=99\n')
        try:w.verify(e);raise AssertionError('out of scope accepted')
        except ValueError as error:assert '범위 밖' in str(error)
        for rel in ('../other','C:/other','.env','secrets/a.py'):
            try:w.prepare(5,dict(spec,paths=[rel]),root,container);raise AssertionError(rel)
            except ValueError:pass
        for argv in (['python','-c','print(1)'],['npm','run','deploy'],['python','harness_test.py','x&whoami']):
            try:w.check_command(argv,repo,spec['paths']);raise AssertionError(argv)
            except ValueError:pass
        # API는 제안만 내고 실제 적용 경계는 서버가 강제한다.
        patcher=WorktreePatchWorker(Path(c['path']),None,c)
        before=Path(c['path']).joinpath('a.py').read_bytes()
        try:
            patcher.apply_payload({'status':'done','message':'test','edits':[
                {'path':'a.py','old':'return 9','new':'return 2'},
                {'path':'../outside.py','old':'x','new':'y'}]})
            raise AssertionError('unsafe patch accepted')
        except ValueError:pass
        assert Path(c['path']).joinpath('a.py').read_bytes()==before
        patcher.apply_payload({'status':'done','message':'test','edits':[{'path':'a.py','old':'return 9','new':'return 2'}]})
        assert 'return 2' in Path(c['path']).joinpath('a.py').read_text()
        patcher=WorktreePatchWorker(Path(c['path']),None,c)
        patcher.apply_payload({'status':'done','message':'full file','files':[{'path':'a.py','content':'def value():\n    return 2\n# kept full file\n'}]})
        assert 'kept full file' in Path(c['path']).joinpath('a.py').read_text()
        print('PASS: real worktree snapshot, dirty source/index preservation, validated source integration, concurrent conflict, failed checks, scope/secret/command boundaries, restart manifest')
        # 깨끗한 원본은 실제 Git fast-forward 병합까지 자동 수행한다.
        clean=root/'clean';clean.mkdir();git(clean,'init');git(clean,'config','user.name','test');git(clean,'config','user.email','test@example.invalid')
        (clean/'a.py').write_text('def value():\n    return 1\n');(clean/'harness_test.py').write_text('from a import value\nassert value()==2\n')
        git(clean,'add','.');git(clean,'commit','-m','base');clean_head=git(clean,'rev-parse','HEAD')
        f=w.prepare(6,dict(spec,repository=str(clean)),root,container)
        Path(f['path']).joinpath('a.py').write_text('def value():\n    return 2\n');w.verify(f);w.integrate(f)
        assert f['integration']=='git-fast-forward' and git(clean,'rev-parse','HEAD')!=clean_head and not git(clean,'status','--porcelain')
        assert Path(f['path']).resolve().is_relative_to(container.resolve());git(clean,'worktree','remove','--force',f['path'])
        # 임시 폴더 삭제 전 Git이 worktree를 정상 등록 해제한다.
        for state in (a,b,c,e):git(repo,'worktree','remove','--force',state['path'])

if __name__=='__main__':check()
