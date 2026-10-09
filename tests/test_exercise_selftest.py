from test_fastapi_service import env, login, book


def provision(client, app, headers):
    bid = book(client, headers)
    with app.state.database.tx() as db:
        db.execute('UPDATE books SET dataset=? WHERE id=?', ('西游记', bid))
    return bid, '/api/books/' + bid


def test_submit_history_stats_and_snapshot(env):
    client, app, _, root = env
    headers, _ = login(client)
    bid, prefix = provision(client, app, headers)
    payload = {'chapters': ['第一回', '第二回']}
    keyed = dict(headers, **{'Idempotency-Key': 'selftest1'})
    start = client.post(prefix + '/exercise-attempts', headers=keyed, json=payload)
    assert start.status_code == 201, start.text
    attempt = start.json()['data']
    assert client.post(prefix + '/exercise-attempts', headers=keyed, json=payload).json()['data'] == attempt
    assert len(attempt['questions']) == 2
    assert all('answer' not in q and 'source' not in q for q in attempt['questions'])
    submit = prefix + '/exercise-attempts/' + attempt['id'] + '/submit'
    empty = client.post(submit, headers=headers, json={'answers': {}})
    assert empty.status_code == 422
    assert empty.json()['message'] == '请先选择答案'
    answers = {'ex001': 1, 'ex002': 0}
    partial = client.post(submit, headers=headers, json={'answers': {'ex001': 1}})
    assert partial.status_code == 422
    invalid = client.post(submit, headers=headers, json={'answers': {'ex001': 99, 'ex002': 0}})
    assert invalid.status_code == 422
    # Grading uses the snapshot even if the bank is removed after starting.
    (root / 'data/exercises_西游记.json').unlink()
    result = client.post(submit, headers=headers, json={'answers': answers})
    assert result.status_code == 200, result.text
    graded = result.json()['data']
    assert graded['accuracy'] == 50
    assert all(q['source'].startswith('《西游记》') for q in graded['questions'])
    assert client.post(submit, headers=headers, json={'answers': answers}).json()['data'] == graded
    assert client.post(submit, headers=headers, json={'answers': {'ex001': 0, 'ex002': 0}}).status_code == 409
    stats = client.get(prefix + '/exercise-statistics', headers=headers).json()['data']
    assert (stats['attempts'], stats['total'], stats['correct'], stats['accuracy']) == (1, 2, 1, 50)
    assert len(stats['chapters']) == 2
    history = client.get(prefix + '/exercise-attempts', headers=headers).json()['data']
    assert history['total'] == 1 and history['items'][0] == graded
    other, _ = login(client, admin=True)
    assert client.post(submit, headers=other, json={'answers': answers}).status_code == 404
    missing = client.post(prefix + '/exercise-attempts', headers=dict(headers, **{'Idempotency-Key': 'missing'}), json=payload)
    assert missing.status_code == 409 and missing.json()['message'] == '习题数据未就绪'


def test_shared_book_history_is_private(env):
    client, app, _, _ = env
    headers, _ = login(client)
    bid, prefix = provision(client, app, headers)
    with app.state.database.tx() as db:
        db.execute("UPDATE books SET visibility='shared' WHERE id=?", (bid,))
    aid = client.post(prefix + '/exercise-attempts', headers=dict(headers, **{'Idempotency-Key': 'shared'}), json={'chapters': ['第一回']}).json()['data']['id']
    client.post(prefix + '/exercise-attempts/' + aid + '/submit', headers=headers, json={'answers': {'ex001': 1}})
    other, _ = login(client, admin=True)
    assert client.get(prefix + '/exercise-attempts', headers=other).json()['data']['total'] == 0
    assert client.get(prefix + '/exercise-statistics', headers=other).json()['data']['total'] == 0
