"""대화 맥락·업무 브리핑 회귀 검사. 운영 DB·AI를 호출하지 않는다."""
import ast
import asyncio
import json
from pathlib import Path
import re
import tempfile
from types import SimpleNamespace
from unittest.mock import patch
from aiohttp import web
from task_router import Router
from task_store import TaskStore
import orchestrator as orch

BASE = Path(__file__).resolve().parent

def functions(*names):
    tree = ast.parse((BASE/'server.py').read_text(encoding='utf-8'))
    return compile(ast.Module(body=[n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name in names], type_ignores=[]), 'server.py', 'exec')

async def check():
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        store = TaskStore(root/'tasks.sqlite')
        router = Router(store)
        for req in ('좋아 최근 업무들 브리핑', '진행 중인 작업 알려줘', '업무 현황 알려줘'):
            assert router.select(req)['contract']['kind'] == 'read', req
        assert router.select('브리핑이란 단어의 뜻은?')['contract']['kind'] == 'text'
        assert router.select('최근 업무 브리핑')['contract']['kind'] == 'read'
        assert all(m['tools'] for m in orch.chain_for('research', lambda _: True, assigned='economy'))
        history = [{'role':'user','text':'최근 업무 브리핑'}, {'role':'jarvis','body':'근거 없는 답변','text':'old'}]
        jobs = []
        async def runner(t):
            jobs.append(t)
        ns = dict(json=json,Path=Path,re=re,asyncio=asyncio,web=web,time=__import__('time'),BASE=root,HQ=root,
                  HISTORY=root/'history.json',UPLOADS=root,TASKS={},TASK_STORE=store,orch=orch,VERSION='test',
                  read_json=lambda p, default: history.copy(),write_json=lambda *a:None,
                  plan_for=lambda req, imgs, provider, checks, parent:dict(router.select(req,imgs,provider,checks,parent),department_id=None),
                  run_orchestrated=runner,run_task=runner,ai_label=lambda _: 'test')
        ns.setdefault('DEDUPE_SECONDS',10);ns.setdefault('UPLOADS',root);exec(functions('attachment_text','gr_message','thread_context','create_task','step_prompt'),ns)
        for body, included in (({'text':'?? 이게 맞아?'},True),({'text':'새 질문','thread':False},False),({'text':'이어줘','thread':True},True)):
            r=await ns['create_task'](body)
            t=ns['TASKS'][r['id']]
            assert ('근거 없는 답변' in t['context']) == included
        try:
            await ns['create_task']({'text':'test','thread':'false'})
            raise AssertionError('invalid thread accepted')
        except web.HTTPBadRequest:
            pass
        t={'req':'최근 업무 브리핑','contract':{'kind':'read'},'context':'prior'}
        prompt=ns['step_prompt'](t,{'id':'s1','title':'test','goal':'brief','depends_on':[]},{},{})
        assert '기록 확인 위치' in prompt and 'progress.md' in prompt and 'prior' in prompt
        await asyncio.sleep(0)
        assert len(jobs)==3
        # 실제 run_step의 확인필요 상태 파싱을 검사한다.
        async def fake_call(*args):
            return '자료를 확인할 수 없습니다.\n[작업상태: 확인필요]',{'input':1,'output':1},'test'
        ns.update(REVIEW_NOTE="review",ROUTER=router,os=__import__('os'),call_model=fake_call)
        exec(functions('run_step'),ns)
        step={'id':'s1'}; task={'id':99,'attempts':[]}
        answer=await ns['run_step'](task,step,'text','test','note',100)
        assert step['status']=='needs_input' and '[작업상태' not in answer
        # 최종 전달 단계까지 확인필요가 보존되는지 실제 실행 함수로 검사한다.
        async def fake_step(t, step, kind, *args, **kwargs):
            step.update(status='needs_input', label='test')
            return '원본 자료가 없습니다.'
        def checkpoint(t, phase, **values):
            t.update(phase=phase, **values)
        async def notify(*args):
            pass
        ns.update(TASK_LIMIT=asyncio.Semaphore(1), execute_assignment=lambda _:None,
                  checkpoint=checkpoint,run_step=fake_step,STEP_NOTE='test',
                  split_files=lambda text:(text,[]), validate_result=lambda *a:[],OUTBOX=root,
                  schedule_backup=lambda:None,notify=notify,taskstate_ko=lambda s:s,
                  sr=type('SR',(),{'gist':staticmethod(lambda text:text)})())
        ns.update(task_instructions=SimpleNamespace(
            build=lambda _: {'text':'fixture rules','sources':[],'skills':[]},
            planner_input=lambda _: '',select_skills=lambda *a: None,resources=lambda _: {}))
        exec(functions('task_prompt','prepare_delegation','review_verdict','run_orchestrated'),ns)
        task={'id':101,'req':'test','attempts':[],'files':[],
              'orchestration':{'mode':'single','single_kind':'text','budget':8000},
              'contract':{'kind':'text','checks':{}}}
        await ns['run_orchestrated'](task)
        assert task['status']=='needs_input' and task['phase']=='delivered', task
        assert '원본 자료가 없습니다.' in (root/'donaro-task-101.md').read_text(encoding='utf-8')
        async def multi_step(t, step, kind, prompt, *args, **kwargs):
            assert 'context-marker' in prompt, kind
            step.update(status='done', label='test', app='test')
            if kind=='plan':
                return json.dumps({'approach':'test','acceptance':['test criterion'],'subtasks':[{'id':'s1'},{'id':'s2'}]})
            if kind=='review':
                return '{"pass":true,"issues":[]}'
            return 'verified result'
        ns.update(run_step=multi_step,SYNTH_NOTE='test',REVIEW_NOTE='test')
        task={'id':102,'provider':'orchestrator','req':'test','context':'context-marker','attempts':[],'files':[],
              'orchestration':{'mode':'multi','budget':24000},'contract':{'kind':'text','checks':{}}}
        await ns['run_orchestrated'](task)
        assert task['status']=='done', task
    print('PASS: briefing routing, tool eligibility, default/explicit thread, validation, prompt sources, needs_input')

if __name__=='__main__':
    asyncio.run(check())



