import subprocess


def git_pull(app):
    cdir = app.dir / 'code'
    proc1 = subprocess.run(['git', 'fetch', '--depth=1'], stderr=subprocess.STDOUT, cwd=cdir)
    proc2 = subprocess.run(['git', 'reset', '--hard', '@{u}'], stderr=subprocess.STDOUT, cwd=cdir)
    return proc1.returncode + proc2.returncode
