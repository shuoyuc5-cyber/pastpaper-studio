"""Test role and classroom boundaries with a new database and authenticated accounts."""
import os
from pathlib import Path
import sys
import tempfile

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

with tempfile.TemporaryDirectory(prefix='pastpaper-classroom-') as directory:
    os.environ['PASTPAPER_DATA_DIR'] = directory
    os.environ['PASTPAPER_LEGACY_GUEST_WRITES'] = '0'
    from app.main import app

    def credentials(username):
        return {'username': username, 'password': 'test-only-passphrase-' + username}

    with TestClient(app) as client:
        created = client.post('/api/auth/register', json=credentials('administrator'))
        assert created.status_code == 200, created.text
        sessions = {'administrator': dict(client.cookies)}
        admin_id = created.json()['user']['id']
        actors = {}
        for name in ('teacher-a', 'teacher-b', 'student-a', 'student-b'):
            response = client.post('/api/admin/accounts', json=credentials(name))
            assert response.status_code == 201, response.text
            account = response.json()
            assert account['role'] == 'student'
            actors[name] = account['id']

        def use(name):
            client.cookies.clear()
            if name not in sessions:
                response = client.post('/api/auth/login', json=credentials(name))
                assert response.status_code == 200, response.text
                sessions[name] = dict(client.cookies)
            else:
                client.cookies.update(sessions[name])

        def role(user_id, new_role, replacement=None):
            return client.put(f'/api/admin/accounts/{user_id}/role', json={'role':new_role,'replacement_id':replacement})

        def create(name, admission='approval'):
            return client.post('/api/classroom/classes', json={
                'name': name, 'subject': 'Mathematics', 'admission': admission, 'capacity': 1
            })

        use('student-a')
        assert create('Forbidden').status_code == 403
        assert role(actors['student-a'], 'teacher').status_code == 403
        use('administrator')
        assert role(admin_id, 'student').status_code == 403
        assert role(actors['teacher-a'], 'admin').status_code == 422
        for name in ('teacher-a', 'teacher-b'):
            assert role(actors[name], 'teacher').status_code == 200
        assert client.get('/api/admin/host-status').json()['database'] is True

        use('teacher-a')
        assert client.get('/api/admin/accounts').status_code == 403
        assert client.get('/api/admin/host-status').status_code == 403
        assert role(actors['teacher-b'], 'student').status_code == 403
        assert client.get('/api/ai/models').status_code == 403
        result = create('Class A')
        assert result.status_code == 201, result.text
        room_a = result.json()
        members_a = f"/api/classroom/classes/{room_a['id']}/members"

        use('teacher-b')
        result = create('Class B', 'automatic')
        assert result.status_code == 201, result.text
        room_b = result.json()
        assert client.get(members_a).status_code == 404
        assert client.put(f"{members_a}/{actors['student-a']}").status_code == 404
        assert client.post('/api/classroom/join', json={'code': room_a['join_code']}).json()['status'] == 'pending'

        use('student-a')
        code = room_a['join_code']
        preview = client.post('/api/classroom/lookup', json={'code': code}).json()
        assert preview['name'] == 'Class A' and 'join_code' not in preview
        assert client.post('/api/classroom/join', json={'code': code}).json()['status'] == 'pending'
        assert client.post('/api/classroom/join', json={'code': code}).json()['status'] == 'pending'
        assert client.get(members_a).status_code == 403
        use('teacher-a')
        assert client.put(f"{members_a}/{actors['student-a']}").status_code == 200
        assert any(row['id'] == actors['student-a'] and row['status'] == 'active'
                   for row in client.get(members_a).json()['members'])
        assert client.post('/api/classroom/join', json={'code': room_b['join_code']}).json()['status'] == 'active'

        use('teacher-b')
        settings = client.put(f"/api/classroom/classes/{room_b['id']}/invitation",
                              json={'enabled': True, 'regenerate': True, 'expires_in_days': 2})
        assert settings.status_code == 200 and settings.json()['join_code'] != room_b['join_code']
        assert client.post('/api/classroom/lookup', json={'code': room_b['join_code']}).status_code == 404
        use('administrator')
        assert role(actors['teacher-a'], 'student').status_code == 409
        assert role(actors['teacher-a'], 'student',actors['student-a']).status_code == 409
        assert role(actors['teacher-a'], 'student',actors['teacher-a']).status_code == 409
        assert role(actors['teacher-a'], 'student',actors['teacher-b']).status_code == 409
        owned_url = '/api/admin/accounts/' + actors['teacher-a'] + '/owned-classes'
        assert client.get(owned_url).json()['eligible_successors'] == [admin_id]
        assert client.delete(f"{members_a}/{actors['teacher-b']}").status_code == 200
        assert actors['teacher-b'] in client.get(owned_url).json()['eligible_successors']
        assert client.delete('/api/admin/accounts/' + actors['teacher-a']).status_code == 409
        assert client.put('/api/admin/accounts/' + actors['teacher-a'] + '/ai-permissions',json={'enabled':False}).status_code == 409
        assert role(actors['teacher-a'], 'student',actors['teacher-b']).json()['transferred_classes'] == 1
        events = client.get('/api/admin/role-audit').json()['events']
        assert len(events) == 3 and events[0]['new_role'] == 'student'

        use('teacher-a')
        assert create('No longer allowed').status_code == 403
        assert client.get(members_a).status_code == 403
        classes = client.get('/api/classroom/classes').json()
        assert classes['managed'] == [] and classes['joined'][0]['id'] == room_b['id']
        use('teacher-b')
        assert client.get(members_a).json()['members'][0]['id'] == actors['student-a']
        use('administrator')
        assert client.delete(f"{members_a}/{actors['student-a']}").status_code == 200
        assert client.delete('/api/admin/accounts/' + actors['teacher-a']).status_code == 200
        use('student-a')
        assert client.get('/api/classroom/classes').json()['joined'] == []
    print('PASS: student defaults, audited teacher grants and revocation, separate classes, private membership, class codes and approval, owner deletion')
