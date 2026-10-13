"""Offline review probes. FAIL means the desired behavior was not met, not a harness error.
Run from the repository root: python -B .work/repository-review/scripts/review_python.py
No real provider calls or image libraries are used. Source files remain unchanged.
"""
import ast
import contextlib
import importlib.util
import inspect
import io
import json
from pathlib import Path
import re
import sys
import tomllib
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
RESULTS = ROOT / '.work/repository-review/results/python_checks.json'
sys.dont_write_bytecode = True
spec = importlib.util.spec_from_file_location('flamin_review', ROOT / '__init__.py', submodule_search_locations=[str(ROOT)])
package = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = package
spec.loader.exec_module(package)
director = sys.modules['flamin_review.nodes.node_prompt_director_ollama']
local = sys.modules['flamin_review.nodes.node_image_prompt_builder_ollama']
grok = sys.modules['flamin_review.nodes.node_image_prompt_builder_grok']
D = director.FlaminGalahNSFWPromptGenerator
L = local.FlaminGalahImageDescriber
G = grok.FlaminGalahGrokImageDescriber
checks = []


def check(name, fn):
    try:
        evidence = fn()
        checks.append({'name': name, 'status': 'PASS', 'evidence': evidence or ''})
    except AssertionError as exc:
        checks.append({'name': name, 'status': 'FAIL', 'evidence': str(exc)})
    except Exception as exc:
        checks.append({'name': name, 'status': 'ERROR', 'evidence': repr(exc)})


def demand(condition, evidence):
    assert condition, evidence
    return evidence


def must_raise(fn, message):
    try:
        result = fn()
    except RuntimeError as exc:
        return 'Rejected as expected: ' + str(exc)
    raise AssertionError(message + '; actual result: ' + repr(result))


RAW = ('integrated_multimodal_description: [Shot 1] A person walks. The shot lasts about 5 seconds.\n\n'
       'overall_soundscape: Footsteps.\n\nnon_diegetic_music: N/A')
ARGS = dict(extra_description='A person walks across a room', camera='static wide shot', style='photorealistic',
            lighting='soft light', duration_seconds=5, include_dialogue=False, dialogue_speaker='the subject',
            dialogue='', dialogue_language='English', soundscape='', music='N/A', extra_details='',
            ollama_model='writer')


def syntax():
    paths = [ROOT / '__init__.py', *sorted((ROOT / 'nodes').glob('*.py'))]
    for path in paths:
        ast.parse(path.read_text(encoding='utf-8'), filename=str(path))
    return f'{len(paths)} Python files parsed successfully'


def metadata_name():
    name = tomllib.loads((ROOT / 'pyproject.toml').read_text(encoding='utf-8'))['project']['name']
    return demand(re.fullmatch(r'[A-Za-z][A-Za-z0-9]*(?:[-_.][A-Za-z0-9]+)*', name),
                  f'Project name {name!r} contains spaces and is not a valid registry ID')


def registrations():
    ids = {'FlaminGalahNSFWPromptGenerator', 'FlaminGalahImageDescriber', 'FlaminGalahGrokImageDescriber'}
    demand(set(package.NODE_CLASS_MAPPINGS) == ids, str(package.NODE_CLASS_MAPPINGS))
    demand(set(package.NODE_DISPLAY_NAME_MAPPINGS) == ids, str(package.NODE_DISPLAY_NAME_MAPPINGS))
    for cls in package.NODE_CLASS_MAPPINGS.values():
        demand(cls.RETURN_TYPES == ('STRING',) and cls.RETURN_NAMES == ('h3_prompt',), str(cls))
    return 'Three node IDs, display names, STRING outputs, and h3_prompt output names are consistent'


def schemas():
    with patch.object(director, '_get_ollama_models', return_value=['vision', 'writer']), patch.object(local, '_get_ollama_models', return_value=['vision', 'writer']):
        for cls in package.NODE_CLASS_MAPPINGS.values():
            schema = cls.INPUT_TYPES()
            parameters = inspect.signature(getattr(cls, cls.FUNCTION)).parameters
            for group in ('required', 'optional'):
                for name in schema.get(group, {}):
                    demand(name in parameters, f'{cls.__name__}: {name} absent from generate signature')
    return 'All required and optional schema inputs have matching generate parameters'


def local_header():
    body = local._format_i2v_output('[shot 1] 2D vector illustration of a bird.', 'Soft feather rustle.')
    demand(body.startswith(local.I2V_FIRST_FRAME_LINE + '\n\n'), body)
    demand(body.count('[Shot 1]') == 2, body)
    demand('Live-action' not in body and body.endswith('non_diegetic_music: N/A'), body)
    return body


def duplicate_header():
    body = local._format_i2v_output(local.I2V_FIRST_FRAME_LINE + '\n\n[Shot 1] A bird.', 'Wing rustle.')
    return demand(body.count(local.I2V_FIRST_FRAME_LINE) == 1, body)


def grok_style():
    body = grok._format_i2va_output('2D vector illustration of a bird logo.', 'Feather rustling.')
    return demand('live-action' not in body.lower(), body)


def grok_shot():
    body = grok._format_i2va_output('[Shot 1] 2D illustration of a bird.', 'Wing rustle.')
    desc = body.split('integrated_multimodal_description: ', 1)[1].split('\n\n', 1)[0]
    return demand(desc.count('[Shot 1]') == 1, desc)


def selected_duration():
    body = D()._force_clean_format(RAW, '', 'N/A', duration_seconds=10)
    return demand('The shot lasts about 10 seconds.' in body and 'about 5 seconds' not in body, body)


def missing_duration():
    body = D()._force_clean_format('integrated_multimodal_description: [Shot 1] A person walks.', '', 'N/A', duration_seconds=10)
    return demand('The shot lasts about 10 seconds.' in body, body)


def disabled_unlabelled():
    body = D()._force_clean_format('integrated_multimodal_description: [Shot 1] A person says <d>Hello</d>.', '', 'N/A')
    return demand('<d>' not in body, body)


def disabled_labelled():
    body = D()._force_clean_format('integrated_multimodal_description: [Shot 1] A person says <d>[English] Hello</d>.', '', 'N/A')
    return demand('<d>' not in body, body)


def exact_other_dialogue_once():
    body = D()._force_clean_format('integrated_multimodal_description: [Shot 1] A person says <d>Hello</d>.', '', 'N/A',
                                   include_dialogue=True, dialogue='Hello', dialogue_language='other')
    return demand(body.count('<d>Hello</d>') == 1, body)


def disabled_sound_dialogue():
    raw = 'integrated_multimodal_description: [Shot 1] A person walks.\n\noverall_soundscape: <d>[English] Hello</d>\n\nnon_diegetic_music: N/A'
    body = D()._force_clean_format(raw, '', 'N/A', include_dialogue=False)
    return demand('<d>' not in body, body)


def failed_vision():
    obj = D()
    captured = []
    def writer(*args, **kwargs):
        captured.append({'prompt': args[0], 'images': kwargs.get('images_b64')})
        return RAW
    with patch.object(obj, '_describe_image', side_effect=RuntimeError('vision unavailable')), patch.object(obj, '_call_ollama', side_effect=writer):
        with contextlib.redirect_stdout(io.StringIO()):
            try:
                output = obj.generate(**ARGS, image=object(), vision_model='vision')
            except RuntimeError as exc:
                return 'Failure propagated: ' + str(exc)
    raise AssertionError('Returned apparently successful I2VA output after vision failure; writer images=' +
                         repr(captured[0]['images']) + '; image description supplied=' +
                         repr('FIRST-FRAME IMAGE DESCRIPTION' in captured[0]['prompt']) + '; output=' + repr(output[0]))


def fallback():
    obj = D()
    with patch.object(obj, '_call_ollama', side_effect=RuntimeError('offline')):
        with contextlib.redirect_stdout(io.StringIO()):
            output = obj.generate(**ARGS)[0]
    return demand(all(field in output for field in ['integrated_multimodal_description: [Shot 1]', 'overall_soundscape:', 'non_diegetic_music: N/A']), output)


class Response:
    def __init__(self, payload):
        self.payload = payload
    def __enter__(self):
        return self
    def __exit__(self, *args):
        return False
    def read(self):
        return json.dumps(self.payload).encode('utf-8')


def reasoning_only():
    with patch('urllib.request.urlopen', return_value=Response({'message': {'content': '', 'thinking': 'I need to inspect the image and decide what to describe.'}})):
        return must_raise(lambda: L()._call_ollama('describe', 'http://mock.invalid', 'vision', 0.2, 'system'),
                          'Reasoning-only response was accepted as final output')


def missing_grok_key():
    with patch.dict('os.environ', {}, clear=True):
        return must_raise(lambda: G()._resolve_key(''), 'Missing API key was not rejected')


def key_precedence():
    with patch.dict('os.environ', {'XAI_API_KEY': 'mock-xai', 'GROK_API_KEY': 'mock-grok'}, clear=True):
        obj = G()
        demand(obj._resolve_key(' mock-widget ') == 'mock-widget', 'Widget precedence failed')
        demand(obj._resolve_key('') == 'mock-xai', 'XAI precedence failed')
    return 'Widget > XAI_API_KEY > GROK_API_KEY; all keys are fake'


def qwen_tags():
    with patch('urllib.request.urlopen', side_effect=OSError('offline')):
        choices = {director.__name__: director._get_ollama_models(), local.__name__: local._get_ollama_models()}
    return demand(all('qwen2.5vl' in names and 'qwen2.5-vl' not in names for names in choices.values()), json.dumps(choices))


def mocked_pipeline(mode, expected_count):
    calls = []
    outputs = iter(['2D bird illustration.', '[Shot 1] 2D bird illustration; the bird gently tilts its head.' if mode == 'Image to Video' else 'A 2D bird illustration.', 'Soft feather rustling.'])
    def model(*args, **kwargs):
        calls.append({'system': args[4], 'images': kwargs.get('images_b64')})
        return next(outputs)
    obj = L()
    with patch.object(local, '_tensor_to_base64_png', return_value='mock-base64'), patch.object(obj, '_call_ollama', side_effect=model):
        output = obj.generate(object(), output_mode=mode, vision_model='vision', prompt_model='writer')[0]
    demand(len(calls) == expected_count, f'{mode}: {len(calls)} calls')
    demand(bool(calls[0]['images']) and all(not c['images'] for c in calls[1:]), str(calls))
    demand(output.startswith(local.I2V_FIRST_FRAME_LINE) if mode == 'Image to Video' else 'integrated_multimodal_description:' not in output, output)
    return f'{mode}: {len(calls)} calls; only first call has image; output={output}'


# Blanket network prohibition: individual HTTP-response tests override it with fake responses.
with patch('urllib.request.urlopen', side_effect=AssertionError('Unexpected network call in offline harness')):
    check('Python syntax', syntax)
    check('Valid registry project name', metadata_name)
    check('Package imports and node registrations', registrations)
    check('Schema-to-function compatibility', schemas)
    check('Local I2V header and illustrated source style', local_header)
    check('Local I2V duplicate header removal', duplicate_header)
    check('Local I2V rejects empty visual description', lambda: must_raise(lambda: local._format_i2v_output('', 'Ambient sound'), 'Empty description accepted'))
    check('Local I2V rejects empty soundscape', lambda: must_raise(lambda: local._format_i2v_output('A bird', ''), 'Empty soundscape accepted'))
    check('Grok preserves illustrated source style', grok_style)
    check('Grok emits one Shot 1 marker in description', grok_shot)
    check('Director honors selected duration', selected_duration)
    check('Director inserts missing duration', missing_duration)
    check('Director removes unlabelled dialogue when disabled', disabled_unlabelled)
    check('Director removes labelled visual dialogue when disabled', disabled_labelled)
    check('Director inserts other-language dialogue exactly once', exact_other_dialogue_once)
    check('Director removes soundscape dialogue when disabled', disabled_sound_dialogue)
    check('Director rejects image path without successful vision', failed_vision)
    check('Director offline text fallback has required structure', fallback)
    check('Local model rejects reasoning-only response', reasoning_only)
    check('Grok rejects missing API key', missing_grok_key)
    check('Grok key precedence', key_precedence)
    check('Ollama fallbacks offer correct official Qwen tag', qwen_tags)
    check('Mocked local Image to Video pipeline', lambda: mocked_pipeline('Image to Video', 3))
    check('Mocked local Image to Image pipeline', lambda: mocked_pipeline('Image to Image', 2))

summary = {state: sum(item['status'] == state for item in checks) for state in ('PASS', 'FAIL', 'ERROR')}
RESULTS.write_text(json.dumps({'summary': summary, 'checks': checks}, indent=2), encoding='utf-8')
for item in checks:
    print(item['status'] + ': ' + item['name'])
    if item['status'] != 'PASS':
        print('  ' + item['evidence'])
print('SUMMARY:', summary)
print('RESULT FILE:', RESULTS)
sys.exit(2 if summary['ERROR'] else 0)
