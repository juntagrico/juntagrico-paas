import random
import string

import psutil


def generate_password():
    return ''.join(random.choice(string.ascii_uppercase + string.digits) for x in range(20))


def generate_secret_key():
    choice = string.ascii_letters
    choice = choice + string.digits
    choice = choice + string.punctuation
    return ''.join(random.choice(choice) for x in range(50))


def pid_finished(pid):
    pid = int(pid)
    return not psutil.pid_exists(pid) or psutil.Process(pid).status() == 'zombie'
