"""Local launcher. Prefer project-local dependencies without changing global Python."""
import os
import runpy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
for folder in ('.api-deps', '.ui-deps'):
    path = ROOT / folder
    if path.is_dir():
        sys.path.insert(0, str(path))


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in ('api', 'ui', 'migrate', 'test'):
        print('Usage: python run_local.py {api|ui|migrate --owner demo|test [pytest arguments]}')
        return 2
    command, args = sys.argv[1], sys.argv[2:]
    if command == 'api':
        import uvicorn
        uvicorn.run('api:create_app', factory=True, host=os.getenv('LITERARY_BIND_HOST', '127.0.0.1'), port=int(os.getenv('LITERARY_API_PORT', '8000')), workers=1, access_log=False)
    elif command == 'ui':
        from streamlit.web import cli
        sys.argv = ['streamlit', 'run', str(ROOT / 'app.py'), '--global.developmentMode=false', '--browser.gatherUsageStats=false', '--server.headless=true', '--server.address=127.0.0.1', '--server.port=' + os.getenv('LITERARY_UI_PORT', '8501')] + args
        return cli.main()
    elif command == 'migrate':
        sys.argv = ['migrate_service.py'] + args
        runpy.run_module('migrate_service', run_name='__main__')
    else:
        import pytest
        return pytest.main(args or ['tests/test_fastapi_service.py', 'tests/test_api_frontend.py', '-q'])
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
