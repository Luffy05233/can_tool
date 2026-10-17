#!/usr/bin/env python3
"""Small direct ClickUp API client; requires only Python's standard library."""
import argparse
import json
import os
from pathlib import Path
import sys
import urllib.error
import urllib.parse
import urllib.request


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def request(path, payload=None):
    token = os.environ.get('CLICKUP_API_TOKEN', '').strip()
    if not token:
        filename = os.environ.get('CLICKUP_TOKEN_FILE', '~/Documents/clickupapi')
        token = Path(filename).expanduser().read_text().strip()
    if not token or any(c.isspace() for c in token):
        raise ValueError('Token must be one nonempty line with no whitespace.')
    req = urllib.request.Request(
        'https://api.clickup.com/api/v2/' + path,
        data=None if payload is None else json.dumps(payload).encode(),
        headers={'Authorization': token, 'Content-Type': 'application/json'},
        method='GET' if payload is None else 'POST',
    )
    try:
        with urllib.request.build_opener(NoRedirect).open(req, timeout=30) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        message = f'ClickUp HTTP {error.code}.'
        if error.code == 429:
            message += ' Rate limit reached; reset time (Unix seconds): ' + error.headers.get('X-RateLimit-Reset', 'unknown')
        raise ValueError(message + ' No automatic retry was attempted.') from None
    except (urllib.error.URLError, TimeoutError):
        raise ValueError('Connection failed. For writes, check ClickUp before retrying to avoid duplicates.') from None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('workspaces')
    for command, argument in [('spaces', 'workspace_id'), ('lists', 'space_id')]:
        commands.add_parser(command).add_argument(argument)
    create = commands.add_parser('create-list')
    create.add_argument('space_id')
    create.add_argument('name')
    tasks = commands.add_parser('tasks')
    tasks.add_argument('list_id')
    tasks.add_argument('--page', type=int, default=0)
    task = commands.add_parser('create-task')
    task.add_argument('list_id')
    task.add_argument('name')
    comments = commands.add_parser('comments')
    comments.add_argument('task_id')
    comments.add_argument('--start')
    comments.add_argument('--start-id')
    comment = commands.add_parser('comment')
    comment.add_argument('task_id')
    comment.add_argument('--file', required=True, help='UTF-8 file containing the message')
    args = parser.parse_args()
    esc = lambda value: urllib.parse.quote(str(value), safe='')
    payload = None
    if args.command == 'workspaces':
        path = 'team'
    elif args.command == 'spaces':
        path = f'team/{esc(args.workspace_id)}/space'
    elif args.command in ('lists', 'create-list'):
        path = f'space/{esc(args.space_id)}/list'
        if args.command == 'create-list':
            payload = {'name': args.name}
    elif args.command in ('tasks', 'create-task'):
        path = f'list/{esc(args.list_id)}/task'
        if args.command == 'create-task':
            payload = {'name': args.name}
        else:
            if args.page < 0:
                parser.error('--page must be nonnegative')
            path += '?' + urllib.parse.urlencode({'page': args.page, 'include_closed': 'true'})
    else:
        path = f'task/{esc(args.task_id)}/comment'
        if args.command == 'comment':
            message = Path(args.file).read_text(encoding='utf-8').strip()
            if not message:
                parser.error('Message file is empty')
            payload = {'comment_text': message, 'notify_all': False}
        elif bool(args.start) != bool(args.start_id):
            parser.error('--start and --start-id must be supplied together')
        elif args.start:
            path += '?' + urllib.parse.urlencode({'start': args.start, 'start_id': args.start_id})
    print(json.dumps(request(path, payload), indent=2))


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError) as error:
        print(f'Error: {error}', file=sys.stderr)
        sys.exit(1)
