"""작업별 Git worktree: 미커밋 스냅샷, 검사, 충돌 없는 원본 반영. 원본 인덱스는 유지한다."""
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys
import threading
import uuid

LOCK = threading.Lock()
SKIP = {'.git','node_modules','__pycache__','.venv','venv','dist','build','coverage','.pytest_cache','task_workspaces','backups','10_GR사업부'}  # GR 원본은 작업 사본에 복사하지 않는다
EXT = {'.py','.js','.jsx','.ts','.tsx','.json','.toml','.yaml','.yml','.md','.html','.css','.sql','.txt','.xml','.sh','.ps1','.bat','.svg'}


def code_change(text, kind):
    return kind == 'write' and bool(re.search(r'코드|버그|앱|서버|웹|개발|\.(?:py|tsx?|jsx?|html|css)\b', text, re.I))


def run(repo, *args, env=None, timeout=90):
    p=subprocess.run(['git','-c','core.quotepath=false','-c','core.hooksPath=NUL',*args],cwd=repo,env=env,
                     stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=timeout)
    if p.returncode:
        raise ValueError('Git '+args[0]+' 실패: '+p.stderr.decode('utf-8','replace')[:400])
    return p.stdout.decode('utf-8','replace').strip()


def path_in(root, rel):
    if not isinstance(rel,str) or not rel or '\\' in rel or re.search(r'[;&|><\r\n\x00"`%!$]',rel) or ':' in rel or PurePosixPath(rel).is_absolute() or any(p in ('','..','.') for p in rel.split('/')):
        raise ValueError('저장소 상대 경로가 필요합니다.')
    p=root.joinpath(*rel.split('/'))
    if not p.resolve().is_relative_to(root.resolve()) or any(q.is_symlink() for q in [p,*p.parents] if q!=root.parent):
        raise ValueError('작업 범위 밖 경로·심볼릭 링크는 허용하지 않습니다.')
    return p


def safe(rel):
    p=PurePosixPath(rel)
    return not any(x in SKIP or x.lower() in ('private','secrets') for x in p.parts) and not any(re.search(r'^(?:\.env|.*(?:token|secret|credential|password).*)', x,re.I) for x in p.parts) and (p.suffix.lower() in EXT or p.name in ('.gitignore','Dockerfile','Makefile'))


def in_scope(rel, scopes):
    return any(rel==s or rel.startswith(s+'/') for s in scopes)


def digest(p):
    return hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else None


def files(root, scopes):
    out={}
    for rel in scopes:
        p=path_in(root,rel)
        candidates=[]
        if p.is_file(): candidates=[p]
        elif p.is_dir():
            for folder,dirs,names in os.walk(p,followlinks=False):
                dirs[:]=[n for n in dirs if n not in SKIP and not (Path(folder)/n).is_symlink()]
                candidates.extend(Path(folder)/n for n in names)
        for f in candidates:
            name=f.relative_to(root).as_posix()
            if not safe(name):continue
            path_in(root,name)
            if f.stat().st_size>5_000_000:raise ValueError('소스 파일 크기 상한 초과: '+name)
            out[name]=digest(f)
    if len(out)>2500:raise ValueError('변경 범위를 프로젝트 단위로 좁혀야 합니다.')
    return out


def save(state):
    p=Path(state['manifest']);p.parent.mkdir(parents=True,exist_ok=True)
    temp=p.with_suffix('.tmp');temp.write_text(json.dumps(state,ensure_ascii=False,indent=2),encoding='utf-8');os.replace(temp,p)


def check_command(argv, root, scopes, directory=None):
    if not isinstance(argv,list) or not argv or any(not isinstance(a,str) or not a or re.search(r'[;&|><\r\n"`%!$]',a) or '..' in a or ':' in a or '\\' in a or re.search(r'(^|=)/',a) for a in argv):
        raise ValueError('검증 명령은 셸 없는 argv 배열이어야 합니다.')
    if argv[0] in ('python','python3'):
        if argv[1:3] == ['-m','py_compile'] and len(argv)>3:
            for name in argv[3:]:
                path_in(root,name)
                if not in_scope((directory+'/' if directory else '')+name,scopes):raise ValueError('컴파일 경로가 작업 범위 밖입니다.')
        elif argv[1:3] in (['-m','unittest'],['-m','pytest']):pass
        elif len(argv)>1 and re.match(r'(?:.*/)?(?:harness_|test_)[\w.-]+\.py$',argv[1]) and in_scope((directory+'/' if directory else '')+argv[1],scopes):path_in(root,argv[1])
        else:raise ValueError('Python 검증은 unittest·pytest·작업 범위의 harness_/test_ 스크립트만 허용합니다.')
        return [sys.executable,*argv[1:]]
    if argv[0]=='npm' and (argv[1:] in (['test'],['run','build'],['run','test'],['run','lint'],['run','check'])):
        exe=shutil.which('npm.cmd' if os.name=='nt' else 'npm')
        if exe:return [exe,*argv[1:]]
    raise ValueError('지원하지 않는 검증 명령입니다.')


def prepare(task_id, spec, hq, container):
    if not isinstance(spec,dict) or set(spec)-{'repository','paths','checks','directory'}:
        raise ValueError('기획자의 code_workspace(저장소·변경 경로·검증 명령)가 필요합니다.')
    repo=Path(spec.get('repository','')).resolve();hq=Path(hq).resolve();container=Path(container).resolve()
    if not repo.is_dir() or not repo.is_relative_to(hq) or Path(run(repo,'rev-parse','--show-toplevel')).resolve()!=repo:
        raise ValueError('본사 안의 Git 저장소 루트를 지정해야 합니다.')
    scopes=spec.get('paths');checks=spec.get('checks')
    if not isinstance(scopes,list) or not 1<=len(scopes)<=20 or len({str(x).casefold() for x in scopes})!=len(scopes):raise ValueError('변경 경로는 1~20개가 필요합니다.')
    for rel in scopes:
        path_in(repo,rel)
        if not safe(rel) and Path(rel).suffix:raise ValueError('비밀값·생성물은 작업 범위가 될 수 없습니다.')
        if any(x in SKIP or x.lower() in ('private','secrets') or x.startswith('.env') for x in rel.split('/')):raise ValueError('보호 경로는 작업 범위가 될 수 없습니다.')
    if not isinstance(checks,list) or not 1<=len(checks)<=5:raise ValueError('실행할 검증 명령이 1~5개 필요합니다.')
    folder=container/str(task_id);folder.mkdir(parents=True,exist_ok=True);manifest=folder/'worktree.json'
    if manifest.exists():
        old=json.loads(manifest.read_text(encoding='utf-8'))
        if old['repo']!=str(repo) or old['scopes']!=scopes:raise ValueError('기존 작업의 저장소·범위와 다릅니다.')
        return old
    destination=(folder/'repo').resolve()
    if not destination.is_relative_to(container) or destination.exists():raise ValueError('worktree 대상 경로가 올바르지 않습니다.')
    directory=spec.get('directory')
    if directory and not in_scope(directory,scopes):raise ValueError('검증 디렉터리는 변경 범위 안이어야 합니다.')
    cwd=path_in(destination,directory) if directory else destination
    for cmd in checks:check_command(cmd,cwd,scopes,directory)
    before=files(repo,scopes);head=run(repo,'rev-parse','HEAD');index=folder/'snapshot.index';env=dict(os.environ,GIT_INDEX_FILE=str(index))
    run(repo,'read-tree',head,env=env)
    tracked=run(repo,'ls-files','-z','--',*scopes).split('\0')
    for rel in tracked:
        if rel and safe(rel) and not path_in(repo,rel).exists():run(repo,'update-index','--force-remove','--',rel,env=env)
    for i in range(0,len(before),100):run(repo,'add','-f','--',*list(before)[i:i+100],env=env)
    tree=run(repo,'write-tree',env=env)
    snapshot=run(repo,'-c','user.name=Codex','-c','user.email=codex@openai.com','commit-tree',tree,'-p',head,'-m',f'Donaro {task_id} source snapshot')
    if before!=files(repo,scopes) or head!=run(repo,'rev-parse','HEAD'):raise ValueError('스냅샷 도중 원본이 바뀌었습니다. 다시 계획해야 합니다.')
    branch=f'donaro/task-{task_id}-{uuid.uuid4().hex[:8]}'
    run(repo,'worktree','add','-b',branch,str(destination),snapshot)
    state=dict(repo=str(repo),path=str(destination),manifest=str(manifest),branch=branch,head=head,snapshot=snapshot,
               scopes=scopes,source_hashes=before,checks=checks,directory=directory,status='prepared')
    save(state)
    if any(cmd[0]=='npm' for cmd in checks) and not (cwd/'node_modules').exists():
        lock=cwd/'package-lock.json'
        if not lock.is_file():raise ValueError('npm 검증에는 package-lock.json이 필요합니다.')
        command=[shutil.which('npm.cmd' if os.name=='nt' else 'npm'),'ci','--ignore-scripts','--no-audit','--no-fund']
        result=subprocess.run(command,cwd=cwd,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=240)
        state['dependency_setup']={'exit_code':result.returncode,'output':result.stdout.decode('utf-8','replace')[-4000:]};save(state)
        if result.returncode:raise ValueError('worktree 의존성 준비 실패. 원본은 변경하지 않았습니다.')
    return state


EXEC_FILES=('conftest.py','package.json','pytest.ini','tox.ini','setup.cfg','pyproject.toml','sitecustomize.py','usercustomize.py')

def verify(state):
    root=Path(state['path']);repo=Path(state['repo']);scopes=state['scopes']
    changed=set(filter(None,run(root,'diff','--name-only',state['snapshot']).splitlines()));allp=set(changed)  # allp: 확장자 거름 없이 모든 변경(실행 설정 파일 검사용)
    # 이 저장소는 신규 소스를 ignore하는 경우도 있어 무시된 텍스트 소스까지 확인한다.
    for flags in (('--others','--exclude-standard'),('--others','--ignored','--exclude-standard')):
        for rel in run(root,'ls-files','-z',*flags).split('\0'):
            if rel:allp.add(rel)
            if rel and safe(rel):changed.add(rel)
    if not changed:raise ValueError('worktree에 변경된 소스가 없습니다.')
    for rel in changed:
        p=path_in(root,rel)
        if not safe(rel) or not in_scope(rel,scopes) or rel.replace('\\','/').startswith('10_GR'):raise ValueError('허용 범위 밖 변경: '+rel)
        if not p.is_file():raise ValueError('파일 삭제는 자동 통합하지 않습니다: '+rel)
        if p.suffix=='.py':compile(p.read_bytes(),str(p),'exec')
        elif p.suffix=='.json':json.loads(p.read_text(encoding='utf-8-sig'))
    before_checks=files(root,scopes)
    logs=[];cwd=path_in(root,state['directory']) if state.get('directory') else root
    exec_files=sorted(r for r in allp if Path(r).name in EXEC_FILES or re.search(r'(^|[./])(vite|webpack|rollup|eslint|babel|jest|vitest|postcss|tailwind)\.config\.|^\.npmrc$|^\.babelrc$',Path(r).name))
    if exec_files:raise ValueError('실행 설정 파일 변경은 사람 검수 후 검증합니다: '+', '.join(exec_files))
    # 검증은 허용 목록 환경으로만 실행한다(작업자가 쓴 코드가 비밀값을 못 보게)
    env={k:os.environ[k] for k in ('PATH','PATHEXT','SYSTEMROOT','SYSTEMDRIVE','COMSPEC','TEMP','TMP','USERPROFILE','APPDATA','LOCALAPPDATA') if k in os.environ}
    home=root/'.verify_home';home.mkdir(exist_ok=True)  # 검증 코드가 실제 홈(자격 증명·설정)을 못 읽게
    env.update(USERPROFILE=str(home),APPDATA=str(home),LOCALAPPDATA=str(home),HOME=str(home),PYTHONDONTWRITEBYTECODE='1',PYTHONNOUSERSITE='1',NO_COLOR='1')
    for argv in state['checks']:
        command=check_command(argv,cwd,scopes,state.get('directory'))
        p=subprocess.run(command,cwd=cwd,env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=180)
        logs.append({'argv':argv,'exit_code':p.returncode,'output':p.stdout.decode('utf-8','replace')[-6000:]})
        state.update(status='validating',tests=logs);save(state)
        if p.returncode:raise ValueError('worktree 검증 실패: '+' '.join(argv))
    # 검증 명령이 소스를 바꾸었다면 그 결과까지 다시 검사한다.
    if files(root,scopes)!=before_checks:raise ValueError('검증 명령이 소스를 바꾸었습니다. 재검증이 필요합니다.')
    run(root,'add','-f','--',*sorted(changed))
    if run(root,'diff','--cached','--name-only'):
        run(root,'-c','user.name=Codex','-c','user.email=codex@openai.com','commit','--no-gpg-sign','-m','Donaro validated task changes')
    diff=run(root,'diff',state['snapshot'],'--',*sorted(changed))
    if len(diff)>100000:raise ValueError('검수할 변경안이 너무 큽니다. 범위를 좁혀야 합니다.')
    state['diff']=diff
    state.update(status='validated',commit=run(root,'rev-parse','HEAD'),changed=sorted(changed),result_hashes={rel:digest(path_in(root,rel)) for rel in changed})
    save(state);return state


def integrate(state):
    with LOCK:
        repo=Path(state['repo']);root=Path(state['path'])
        if state['status']=='integrated':return state
        if state['status']!='validated':raise ValueError('검증 완료 전에는 원본에 반영할 수 없습니다.')
        if run(repo,'rev-parse','HEAD')!=state['head']:raise ValueError('기준 커밋이 바뀌어 자동 통합하지 않았습니다.')
        if files(repo,state['scopes']) != state['source_hashes']:raise ValueError('원본 프로젝트 변경 충돌: 검증 기준이 바뀌었습니다.')
        if files(repo,state['scopes']) != state['source_hashes']:raise ValueError('원본 프로젝트 변경 충돌: 검증 기준이 바뀌었습니다.')
        for rel in state['changed']:
            if digest(path_in(repo,rel))!=state['source_hashes'].get(rel):raise ValueError('원본 변경 충돌: '+rel)
            if digest(path_in(root,rel))!=state['result_hashes'][rel]:raise ValueError('검증 후 worktree 소스가 바뀌었습니다: '+rel)
        if not run(repo,'status','--porcelain','--untracked-files=all') and files(repo,state['scopes'])==state['source_hashes']:
            run(repo,'merge','--ff-only','--no-edit',state['branch'])
            state.update(status='integrated',integration='git-fast-forward',source_head_unchanged=False)
            save(state);return state
        # 미커밋 파일·인덱스가 있으면 원본에서는 commit/checkout/reset/stash를 하지 않는다.
        backup=Path(state['manifest']).parent/'integration_backup';applied=[]
        state.update(status='integrating');save(state)
        try:
            for rel in state['changed']:
                target=path_in(repo,rel);saved=backup/rel
                if target.exists():saved.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(target,saved)
                target.parent.mkdir(parents=True,exist_ok=True)
                temp=target.with_name(target.name+'.donaro-'+uuid.uuid4().hex+'.tmp')
                temp.write_bytes(path_in(root,rel).read_bytes())
                if digest(target)!=state['source_hashes'].get(rel):raise ValueError('통합 직전 원본 변경 충돌: '+rel)
                os.replace(temp,target);applied.append(rel)
        except Exception:
            for rel in reversed(applied):
                target=path_in(repo,rel);saved=backup/rel
                if digest(target)!=state['result_hashes'][rel]:continue
                if saved.exists():shutil.copy2(saved,target)
                else:target.unlink()
            state.update(status='needs_reconciliation');save(state);raise
        state.update(status='integrated',integration='source-files',source_head_unchanged=True)
        save(state);return state
