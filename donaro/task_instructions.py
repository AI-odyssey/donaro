"""기획자·실행자가 공유하는 지침 스냅샷. 키·사용자 첨부를 지침으로 읽지 않는다."""
import hashlib
import re
from pathlib import Path

HOME = Path.home()
HQ = HOME / '본사'
BASE = Path(__file__).resolve().parent
SKILL_ROOTS = (HOME/'.agents/skills', HOME/'.codex/skills')


def catalog():
    out = {}
    for root in SKILL_ROOTS:
        for pattern in ('*/SKILL.md', 'synced/*/*/SKILL.md', '.system/*/SKILL.md'):
            for path in sorted(root.glob(pattern)):
                name = path.parent.name
                if name in out:
                    continue
                body = path.read_text(encoding='utf-8-sig')
                desc = re.search(r'^description:\s*(.+)', body, re.M)
                out[name] = {'path': str(path), 'description': desc[1].strip(' "')[:160] if desc else name}
    return out


def add(bundle, path, kind):
    path = Path(path)
    if any(s['path'] == str(path) for s in bundle['sources']):
        return
    body = path.read_text(encoding='utf-8-sig')
    if len(body) > 100000:
        raise ValueError(f'지침이 너무 큽니다: {path.name}')
    bundle['sources'].append({'path': str(path), 'kind': kind,
                              'sha256': hashlib.sha256(body.encode()).hexdigest(), 'chars': len(body)})
    bundle['text'] += f'\n\n[적용 지침: {path}]\n{body}'


def text_for(bundle, kinds):
    """저장 구조는 그대로 두고, kind가 kinds인 지침 원문만 다시 읽어 이어 붙인다(단계별 입력 축소용)."""
    out = []
    for x in bundle['sources']:
        if x['kind'] not in kinds:
            continue
        body = Path(x['path']).read_text(encoding='utf-8-sig')
        if hashlib.sha256(body.encode()).hexdigest() != x['sha256']:
            return bundle['text']  # 작업 중 지침이 바뀌었으면 기록된 원문 묶음 전체를 쓴다(기록 sha와 실제 입력 일치)
        out.append(f"\n\n[적용 지침: {x['path']}]\n" + body)
    return ''.join(out)


def build(department_id=None):
    bundle = {'text': '', 'sources': [], 'skills': [], 'catalog': catalog()}
    for folder in [HQ, *(sorted(HQ.glob(str(department_id)+'_*')) if department_id else [])]:
        primary = folder/'AGENTS.md'
        if not primary.exists():
            primary = folder/'CLAUDE.md'
        if primary.exists():
            add(bundle, primary, 'common' if folder==HQ else 'department')
        if folder != HQ and (folder/'지침.md').exists():
            add(bundle, folder/'지침.md', 'department')
    add(bundle, BASE/'DONARO.md', 'policy')
    return bundle


def select_skills(bundle, names):
    if not isinstance(names, list) or len(names)>8 or any(not isinstance(n,str) for n in names):
        raise ValueError('기획자의 스킬 선택 형식 오류')
    for name in names:
        if name not in bundle['catalog']:
            raise ValueError(f'설치되지 않은 스킬: {name}')
        if name not in bundle['skills']:
            add(bundle, bundle['catalog'][name]['path'], 'skill')
            bundle['skills'].append(name)


def planner_input(bundle):
    return '\n\n[선택 가능한 설치 스킬: 이름은 본문 로드 완료를 뜻하지 않음]\n' + '\n'.join(
        f"{name}: {meta['description']}" for name,meta in bundle['catalog'].items())


def resources(bundle):
    """선택한 스킬 폴더 안의 텍스트 참조만 후보로 제공한다. 임의 경로는 읽지 않는다."""
    out={}
    for name in bundle['skills']:
        root=Path(bundle['catalog'][name]['path']).resolve().parent
        candidates=set()
        for dirname in ('reference','references','rules'):
            folder=root/dirname
            if folder.is_dir():candidates.update(folder.rglob('*.md'))
        for path in candidates:
            if path.is_file() and not path.is_symlink() and path.resolve().is_relative_to(root):
                out[name+'/'+path.relative_to(root).as_posix()]=str(path)
    return out


def select_resources(bundle, names, available):
    if not isinstance(names,list) or len(names)>12 or any(not isinstance(n,str) or n not in available for n in names):
        raise ValueError('스킬 참조 문서 선택 오류')
    for name in names:add(bundle,available[name],'skill-resource')
