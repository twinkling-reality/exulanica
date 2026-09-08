"""Restore exactly the baseline record_consent writer in this child process."""
def pytest_sessionstart(session: object) -> None:
    import ast
    import subprocess

    from exulanica.ingest import person_review

    revision = '802f902c3cacb631ab80bf43f4348ddbe67734a2:exulanica/ingest/person_review.py'
    source = subprocess.check_output(['git', 'show', revision], text=True)
    tree = ast.parse(source)
    function = next(
        n for n in tree.body
        if isinstance(n, ast.FunctionDef) and n.name == 'record_consent'
    )
    module = ast.Module(body=[function], type_ignores=[])
    exec(compile(module, '<baseline-writer>', 'exec'), person_review.__dict__)
