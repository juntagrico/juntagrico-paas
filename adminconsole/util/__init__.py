import secrets
import string

import psutil


def generate_password():
    return ''.join(secrets.choice(string.ascii_uppercase + string.digits) for x in range(20))


def generate_secret_key():
    choice = string.ascii_letters
    choice = choice + string.digits
    choice = choice + string.punctuation
    return ''.join(secrets.choice(choice) for x in range(50))


def pid_finished(pid):
    """
    True if the process has ended. Processes not started by the console (same user, `-m manage`) also count as
    ended, so the answer reveals nothing about other processes on the server.
    """
    try:
        process = psutil.Process(int(pid))
        if process.status() == psutil.STATUS_ZOMBIE:
            return True
        return process.username() != psutil.Process().username() or 'manage' not in process.cmdline()
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
        return True
