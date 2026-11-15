"""실제 Git worktree와 가짜 AI로 운영 run_task의 생성→검증→원본 반영 경로를 검사한다."""
import asyncio
import json
import os
from pathlib import Path
import re
import tempfile
import time
from types import SimpleNamespace
import orchestrator as orch
import task_worktrees
from task_store import TaskStore
from harness_context import functions
from harness_worktrees import git

async def check():
    with tempfile.TemporaryDirectory() as d:
        root=Path(d);repo=root/'repo';repo.mkdir();base=root/'server';base.mkdir()
        git(repo,'init');git(repo,'config','user.name','test');git(repo,'config','user.email','test@example.invalid')
        (repo/'a.py').write_text('def value():\n    return 1\n# user work\n')
        (repo/'harness_test.py').write_text('from a import value\nassert value()==2\n')
        git(repo,'add','.');git(repo,'commit','-m','base')
        asked=[]
        class FakeWorker:
            fail=False
            usage={};evidence={};tools_used=True
            def __init__(self,workspace,router,state,**kwargs):
                self.workspace=workspace;assert state["path"]==str(workspace)
            async def ask(self,prompt,emit):
                if self.fail:raise ValueError('proposal mismatch')
                assert str(self.workspace) in prompt and '격리 worktree' in prompt
                p=self.workspace/'a.py';p.write_text(p.read_text().replace('return 1','return 2'))
                asked.append(self.workspace);return ['수정·테스트 준비 완료\n[작업상태: 완료]']
        async def reviewed(t,result):
            assert t['worktree']['status']=='validated' and t['evidence']['worktree']['tests'][0]['exit_code']==0
            return True
        async def noop(*args):pass
        def checkpoint(t,phase,**values):t.update(phase=phase,**values)
        store=TaskStore(root/'tasks.sqlite')
        ns=dict(task_worktrees=task_worktrees,asyncio=asyncio,Path=Path,os=os,time=time,json=json,re=re,orch=orch,
                BASE=base,HQ=root,OUTBOX=base,UPLOADS=base,HISTORY=base/'history.json',TASK_STORE=store,TASKS={},
                WorktreePatchWorker=FakeWorker,TASK_LIMIT=asyncio.Semaphore(1),checkpoint=checkpoint,
                release_task_worker=lambda _:None,review_delegated=reviewed,split_files=lambda t:(t,[]),validate_result=lambda *a:[],
                read_json=lambda *a:[],write_json=lambda *a:None,schedule_backup=lambda:None,notify=noop,taskstate_ko=lambda s:s,
                sr=SimpleNamespace(gist=lambda t:t),ROUTER=SimpleNamespace(select=lambda *a:{'engine':'claude','model':'opus','reason':'fixture'},available=lambda _:True,success=lambda *a:None))
        exec(functions('friendly_error','task_prompt','selected_worker','prepare_delegation','run_task'),ns)
        spec={'repository':str(repo),'paths':['a.py','harness_test.py'],'checks':[['python','harness_test.py']]}
        t={'id':101,'req':'a.py 코드 수정','provider':'claude','requested_provider':'auto','result':'','files':[],'attempts':[],
           'instructions':{'text':'fixture rules'},'orchestration':{'prepared':True,'approach':'test','workspace':'worktree','acceptance':['passes'],'subtasks':[], 'code_workspace':spec},
           'contract':{'kind':'write','checks':{},'deadline_seconds':30,'max_attempts':2}}
        await ns['run_task'](t)
        assert t['status']=='done' and t['worktree']['status']=='integrated',t
        assert 'return 2' in (repo/'a.py').read_text() and 'user work' in (repo/'a.py').read_text()
        assert asked and not git(repo,'diff','--cached')
        assert Path(t['worktree']['path']).resolve().is_relative_to((base/'task_workspaces').resolve())
        first=t['worktree']['path'];before=(repo/'a.py').read_bytes()
        FakeWorker.fail=True
        t2={'id':102,'req':'a.py 코드 수정','provider':'claude','requested_provider':'auto','result':'','files':[],'attempts':[],
            'instructions':{'text':'fixture rules'},'orchestration':{'prepared':True,'approach':'test','workspace':'worktree','acceptance':['passes'],'subtasks':[],'code_workspace':spec},
            'contract':{'kind':'write','checks':{},'deadline_seconds':30,'max_attempts':2}}
        await ns['run_task'](t2)
        assert t2['status']=='needs_reconciliation' and t2['attempts'][-1].get('finished') and t2['attempts'][-1].get('error'),t2
        assert (repo/'a.py').read_bytes()==before
        for target in (first,t2['worktree']['path']):
            assert Path(target).resolve().is_relative_to((base/'task_workspaces').resolve())
            git(repo,'worktree','remove','--force',target)
        print('PASS: actual server lifecycle creates writable isolated executor, validates tests, reviews evidence, integrates source and preserves index')

if __name__=='__main__':asyncio.run(check())
