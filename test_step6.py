"""验证 loader 完善项的集成测试"""
import json, os, sys, tempfile
from pathlib import Path
sys.path.insert(0, '.')

from mybot.config.loader import (
    set_config_path, get_config_path, load_config, save_config,
    DEFAULT_CONFIG_PATH,
)

def test_default_path():
    assert get_config_path() == DEFAULT_CONFIG_PATH, '默认路径应为 ~/.mybot/config.json'
    print('  [OK] get_config_path 默认值')

def test_set_get():
    test_path = Path(tempfile.gettempdir()) / 'mybot_test_config.json'
    set_config_path(test_path)
    assert get_config_path() == test_path, 'set 后 get 应返回新值'
    print('  [OK] set_config_path -> get_config_path')
    return test_path

def test_load_config(test_path):
    config_json = {'providers': {'openai': {'apiKey': 'sk-test123', 'model': 'gpt-4'}}}
    os.makedirs(test_path.parent, exist_ok=True)
    with open(test_path, 'w', encoding='utf-8') as f:
        json.dump(config_json, f)

    config = load_config(test_path)
    assert config.providers.openai.model == 'gpt-4'
    assert config.providers.openai.api_key == 'sk-test123'
    print('  [OK] load_config 读取 + camelCase->snake_case 转换')
    return config

def test_save_config(config, test_path):
    save_config(config, test_path)
    with open(test_path, 'r', encoding='utf-8') as f:
        saved = json.load(f)
    assert saved['providers']['openai']['apiKey'] == 'sk-test123'
    assert saved['providers']['openai']['model'] == 'gpt-4'
    print('  [OK] save_config 写回 camelCase JSON')

def test_env_var_resolution(test_path):
    os.environ['MYBOT_TEST_VAR'] = 'resolved_value'
    config_json = {'providers': {'openai': {'apiKey': '${MYBOT_TEST_VAR}'}}}
    with open(test_path, 'w', encoding='utf-8') as f:
        json.dump(config_json, f)

    config2 = load_config(test_path)
    assert config2.providers.openai.api_key == 'resolved_value', (
        f'env var 未解析: got={config2.providers.openai.api_key!r}'
    )
    print('  [OK] ${MYBOT_TEST_VAR} 环境变量替换')

def test_paths_lazy_import(test_path):
    set_config_path(test_path)
    from mybot.config.paths import get_config_path as paths_get_config_path
    result = paths_get_config_path()
    assert result == test_path, f'paths 转发失败: {result} != {test_path}'
    print('  [OK] paths.get_config_path() 懒加载转发')

if __name__ == '__main__':
    print('=== Test Step 6: loader 完善 ===')
    test_default_path()
    tp = test_set_get()
    cfg = test_load_config(tp)
    test_save_config(cfg, tp)
    test_env_var_resolution(tp)
    test_paths_lazy_import(tp)

    # cleanup
    os.remove(tp)
    print()
    print('====== 6/6 全部通过 ======')
