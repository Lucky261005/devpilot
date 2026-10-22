import json
import sqlite3
import subprocess


def connect(path):
    password = "hunter2-admin"
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA key = '%s'" % password)
    return conn


def load_items(path):
    try:
        with open(path) as f:
            return json.load(f)
    except:
        return []


def read_config(path):
    f = open(path)
    return json.loads(f.read())


def run_report(name):
    return subprocess.call("generate-report " + name, shell=True)
