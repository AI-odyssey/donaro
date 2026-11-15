"""상위 기획·지침 본문·권한·검수 회귀 검사. 실제 모델과 운영 DB를 사용하지 않는다."""
import asyncio
import json
import os
from pathlib import Path
import re
import tempfile
import time
from types import SimpleNamespace
from unittest.mock import patch
import orchestrator as orch
import task_instructions as instructions
from task_store import TaskStore
from task_router import Router
from task_workers import WorktreePatchWorker
from harness_context import functions

async def check():
    with tempfile.TemporaryDirectory() as d:
        root=Path(d); hq=root/'hq'; hq.mkdir(); (hq/'40_개발랩').mkdir()
        (hq/'AGENTS.md').write_text('COMMON-MARKER',encoding='utf-8')
        (hq/'40_개발랩'/'지침.md').write_text('DEPT-MARKER',encoding='utf-8')
        skills=root/'skills'; (skills/'fixture').mkdir(parents=True)
        (skills/'fixture'/'reference').mkdir(); (skills/'fixture'/'reference'/'required.md').write_text('RESOURCE-BODY-MARKER',encoding='utf-8')
        skill=skills/'fixture'/'SKILL.md'; skill.write_text('---\ndescription: fixture test\n---\nSKILL-BODY-MARKER',encoding='utf-8')
        (root/'DONARO.md').write_text('POLICY-MARKER',encoding='utf-8')
        with patch.multiple(instructions,HQ=hq,BASE=root,SKILL_ROOTS=(skills,)):
            bundle=instructions.build('40')
            assert 'COMMON-MARKER' in bundle['text'] and 'DEPT-MARKER' in bundle['text']
            assert 'SKILL-BODY-MARKER' not in instructions.planner_input(bundle)
            instructions.select_skills(bundle,['fixture'])
            assert 'SKILL-BODY-MARKER' in bundle['text']
            assert all(len(s['sha256'])==64 for s in bundle['sources'])
            before=len(bundle['sources']); instructions.select_skills(bundle,['fixture']); assert len(bundle['sources'])==before
            try:
                instructions.select_skills(bundle,['missing'])
                raise AssertionError('unknown skill accepted')
            except ValueError:
                pass
            store=TaskStore(root/'tasks.sqlite')
            captured=[]
            async def fake_step(t,step,kind,prompt,*args,**kwargs):
                t['attempts'].append({'step':step['id']});step['status']='done';captured.append((kind,prompt))
                if kind=='review': return '{"pass":true,"issues":[]}'
                if step['id']=='skill_resources':return '{"resources":["fixture/reference/required.md"]}'
                return json.dumps({'approach':'delegate','skills':['fixture'],'workspace':'worktree for code',
                                   'acceptance':['answer contains evidence'],'subtasks':[{'id':'s1','kind':'text','goal':'do test'}]})
            ns=dict(task_instructions=instructions,orch=orch,TASK_STORE=store,Path=Path,json=json,re=re,
                    BASE=root,HQ=hq,OUTBOX=root,TASKS={},run_step=fake_step,REVIEW_NOTE="review",SYNTH_NOTE="synth",RESOURCE_NOTE="resource",STAGE_KINDS={})
            exec(functions('task_prompt','prepare_delegation','review_verdict','review_delegated'),ns)
            t={'id':1,'req':'test','provider':'claude','attempts':[],'contract':{'kind':'read'},'department_id_rule':'40'}
            plan=await ns['prepare_delegation'](t)
            assert plan['subtasks'][0]['kind']=='research'
            assert 'SKILL-BODY-MARKER' in t['instructions']['text'] and 'RESOURCE-BODY-MARKER' in t['instructions']['text']
            assert t['orchestration']['prepared'] and t['orchestration']['workspace'].startswith('worktree')
            assert await ns['review_delegated'](t,'evidence answer')
            for bad in ('{}','{"pass":"yes","issues":[]}','text only'):
                try:
                    ns['review_verdict'](bad);raise AssertionError('invalid review accepted')
                except ValueError:
                    pass
            async def reject(t,step,kind,*args,**kwargs):
                step['status']='done';return '{"pass":false,"issues":["missing evidence"]}'
            ns['run_step']=reject;t['contract']['kind']='write'
            assert not await ns['review_delegated'](t,'changed') and t['status']=='needs_reconciliation'
            # 실제 API 어댑터 호출 직전에 본문이 시스템 지침으로 들어가는지 확인.
            received=[]
            class FakeAPI:
                def __init__(self,*args,**kwargs):self.usage={}
                async def ask(self,message,emit):
                    received.append((self.system_note,message));return ['answer']
                def kill(self):pass
            ns.update(WorktreePatchWorker=WorktreePatchWorker,EconomyWorker=FakeAPI,ROUTER=None,asyncio=asyncio,STEP_TIMEOUT={'api':1},POOL=[],usage_of=lambda _: {'input':0,'output':0})
            exec(functions('call_model'),ns)
            await ns['call_model'](t,orch.BY_ID['codex-sol-api'],'task',100,'note')
            assert all(marker in received[0][0] for marker in ('COMMON-MARKER','DEPT-MARKER','SKILL-BODY-MARKER'))
            assert received[0][1]=='task'
        # 기획 시도가 실행 재시도 예산을 소모하지 않는지 실제 기존 실행 루프로 검사.
        asked=[]
        class FakeWorker:
            usage={'input_tokens':1,'output_tokens':1}
            evidence={}
            async def ask(self,prompt,emit):
                asked.append(prompt);return ['verified answer\n[작업상태: 완료]']
        async def pass_review(*args):return True
        async def notify(*args):pass
        def checkpoint(t,phase,**values):t.update(phase=phase,**values)
        ns.update(time=time,os=os,selected_worker=lambda _:FakeWorker(),release_task_worker=lambda _:None,
                  ROUTER=SimpleNamespace(select=lambda *a: {'engine':'claude','model':'opus','reason':'fixture'},success=lambda *a:None),
                  TASK_LIMIT=asyncio.Semaphore(1),checkpoint=checkpoint,review_delegated=pass_review,
                  split_files=lambda text:(text,[]),validate_result=lambda *a:[],HISTORY=root/'history.json',
                  read_json=lambda *a:[],write_json=lambda *a:None,schedule_backup=lambda:None,
                  notify=notify,taskstate_ko=lambda s:s,sr=SimpleNamespace(gist=lambda t:t))
        exec(functions('run_task'),ns)
        t={'id':77,'req':'test','provider':'claude','requested_provider':'auto','result':'','files':[],
           'instructions':bundle,'attempts':[{'step':'plan'},{'step':'plan'}],
           'orchestration':{'prepared':True,'approach':'test','workspace':'worktree','acceptance':['test'],'subtasks':[]},
           'contract':{'kind':'text','checks':{},'deadline_seconds':10,'max_attempts':2}}
        await ns['run_task'](t)
        assert t['status']=='done' and len(asked)==1,t
        assert 'SKILL-BODY-MARKER' in asked[0]
        # 배정 선호가 있어도 저가 모델이 상위 모델보다 앞설 수 없다.
        for kind in orch.CHAINS:
            assert orch.chain_for(kind,lambda _:True,assigned='economy')[0]['tier']==3,kind
        assert orch.chain_for('plan',lambda h:h!='claude_native')[0]['id']=='codex-sol-api'
        assert all(m['app'] in ('claude','codex') for m in orch.chain_for('plan',lambda _:True))
        assert all(m['tools'] for m in orch.chain_for('research',lambda _:True))
        assert orch.needs_plan('짧은 요청','text')
        assert orch.is_quota("You've hit your 5-hour limit · resets 11:30pm (Asia/Seoul)")
        router=Router(store)
        # 23:26 KST 관측이면 명시된 23:30까지만 기다린다(기존 고정 1시간 금지).
        from datetime import datetime,timezone,timedelta
        observed=datetime(2026,11,13,23,26,tzinfo=timezone(timedelta(hours=9))).timestamp()
        router.failure('claude_native',"You've hit your 5-hour limit · resets 11:30pm (Asia/Seoul)",observed_at=observed)
        health=router.health('claude_native')
        assert health['state']=='quota' and health['next_probe_at']-observed==240,health
    print('PASS: instruction/skill bodies, source hashes, unknown skills, planner read capability, strict review, write reconciliation, API injection, high-model priority')

if __name__=='__main__':asyncio.run(check())


