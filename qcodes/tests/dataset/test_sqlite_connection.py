import sqlite3

import pytest

from qcodes.dataset.sqlite_base import ConnectionPlus, \
    make_plus_connection_from, atomic, connect


def sqlite_conn_in_transaction(conn: sqlite3.Connection):
    assert isinstance(conn, sqlite3.Connection)
    assert True is conn.in_transaction
    assert None is conn.isolation_level
    return True


def plus_conn_in_transaction(conn: ConnectionPlus):
    assert isinstance(conn, ConnectionPlus)
    assert True is conn.atomic_in_progress
    assert None is conn.isolation_level
    assert True is conn.in_transaction
    return True


def sqlite_conn_is_idle(conn: sqlite3.Connection, isolation=None):
    assert isinstance(conn, sqlite3.Connection)
    assert False is conn.in_transaction
    assert isolation == conn.isolation_level
    return True


def plus_conn_is_idle(conn: ConnectionPlus, isolation=None):
    assert isinstance(conn, ConnectionPlus)
    assert False is conn.atomic_in_progress
    assert isolation == conn.isolation_level
    assert False is conn.in_transaction
    return True


def test_connection_plus():
    sqlite_conn = sqlite3.connect(':memory:')
    plus_conn = ConnectionPlus(sqlite_conn)

    assert isinstance(plus_conn, ConnectionPlus)
    assert isinstance(plus_conn, sqlite3.Connection)
    assert False is plus_conn.atomic_in_progress


@pytest.mark.parametrize(
    argnames='conn',
    argvalues=(sqlite3.connect(':memory:'),
               ConnectionPlus(sqlite3.connect(':memory:'))),
    ids=('sqlite3.Connection', 'ConnectionPlus')
)
def test_make_plus_connection_from(conn):
    plus_conn = make_plus_connection_from(conn)

    assert isinstance(plus_conn, ConnectionPlus)

    if isinstance(conn, ConnectionPlus):
        assert conn.atomic_in_progress is plus_conn.atomic_in_progress
    else:
        assert False is plus_conn.atomic_in_progress


def test_atomic_on_outmost_sqlite_connection():
    sqlite_conn = sqlite3.connect(':memory:')
    isolation_level = sqlite_conn.isolation_level
    assert False is sqlite_conn.in_transaction

    with atomic(sqlite_conn) as atomic_conn:
        assert sqlite_conn_in_transaction(sqlite_conn)
        assert plus_conn_in_transaction(atomic_conn)

    assert sqlite_conn_is_idle(sqlite_conn, isolation_level)
    assert plus_conn_is_idle(atomic_conn, isolation_level)


def test_atomic_on_outmost_plus_connection():
    sqlite_conn = sqlite3.connect(':memory:')
    plus_conn = ConnectionPlus(sqlite_conn)
    assert False is plus_conn.atomic_in_progress

    atomic_in_progress = plus_conn.atomic_in_progress
    isolation_level = plus_conn.isolation_level

    assert False is plus_conn.in_transaction

    with atomic(plus_conn) as atomic_conn:
        assert plus_conn_in_transaction(atomic_conn)
        assert plus_conn_in_transaction(plus_conn)

    assert isolation_level == plus_conn.isolation_level
    assert False is plus_conn.in_transaction
    assert atomic_in_progress is plus_conn.atomic_in_progress

    assert isolation_level == plus_conn.isolation_level
    assert False is atomic_conn.in_transaction
    assert atomic_in_progress is atomic_conn.atomic_in_progress


@pytest.mark.parametrize('in_transaction', (True, False))
def test_atomic_on_outmost_plus_connection_that_is_in_progress(in_transaction):
    sqlite_conn = sqlite3.connect(':memory:')
    plus_conn = ConnectionPlus(sqlite_conn)

    # explicitly set to True for testing purposes
    plus_conn.atomic_in_progress = True

    # implement parametrizing over connection's `in_transaction` attribute
    if in_transaction:
        plus_conn.cursor().execute('BEGIN')
    assert in_transaction is plus_conn.in_transaction

    isolation_level = plus_conn.isolation_level
    in_transaction = plus_conn.in_transaction

    with atomic(plus_conn) as atomic_conn:
        assert True is plus_conn.atomic_in_progress
        assert isolation_level == plus_conn.isolation_level
        assert in_transaction is plus_conn.in_transaction

        assert True is atomic_conn.atomic_in_progress
        assert isolation_level == atomic_conn.isolation_level
        assert in_transaction is atomic_conn.in_transaction

    assert True is plus_conn.atomic_in_progress
    assert isolation_level == plus_conn.isolation_level
    assert in_transaction is plus_conn.in_transaction

    assert True is atomic_conn.atomic_in_progress
    assert isolation_level == atomic_conn.isolation_level
    assert in_transaction is atomic_conn.in_transaction


def test_two_atomics_on_outmost_sqlite_connection():
    sqlite_conn = sqlite3.connect(':memory:')

    isolation_level = sqlite_conn.isolation_level
    assert False is sqlite_conn.in_transaction

    with atomic(sqlite_conn) as atomic_conn_1:
        assert sqlite_conn_in_transaction(sqlite_conn)
        assert plus_conn_in_transaction(atomic_conn_1)

        with atomic(atomic_conn_1) as atomic_conn_2:
            assert sqlite_conn_in_transaction(sqlite_conn)
            assert plus_conn_in_transaction(atomic_conn_2)
            assert plus_conn_in_transaction(atomic_conn_1)

        assert sqlite_conn_in_transaction(sqlite_conn)
        assert plus_conn_in_transaction(atomic_conn_1)
        assert plus_conn_in_transaction(atomic_conn_2)

    assert sqlite_conn_is_idle(sqlite_conn, isolation_level)
    assert plus_conn_is_idle(atomic_conn_1, isolation_level)
    assert plus_conn_is_idle(atomic_conn_2, isolation_level)


def test_two_atomics_on_outmost_plus_connection():
    sqlite_conn = sqlite3.connect(':memory:')
    plus_conn = ConnectionPlus(sqlite_conn)

    atomic_in_progress = plus_conn.atomic_in_progress
    isolation_level = plus_conn.isolation_level

    assert False is plus_conn.in_transaction

    with atomic(plus_conn) as atomic_conn_1:
        assert plus_conn_in_transaction(plus_conn)
        assert plus_conn_in_transaction(atomic_conn_1)

        with atomic(atomic_conn_1) as atomic_conn_2:
            assert plus_conn_in_transaction(plus_conn)
            assert plus_conn_in_transaction(atomic_conn_1)
            assert plus_conn_in_transaction(atomic_conn_2)

        assert plus_conn_in_transaction(plus_conn)
        assert plus_conn_in_transaction(atomic_conn_1)
        assert plus_conn_in_transaction(atomic_conn_2)

    assert plus_conn_is_idle(plus_conn, isolation_level)
    assert plus_conn_is_idle(atomic_conn_1, isolation_level)
    assert plus_conn_is_idle(atomic_conn_2, isolation_level)

    assert atomic_in_progress == plus_conn.atomic_in_progress
    assert atomic_in_progress == atomic_conn_1.atomic_in_progress
    assert atomic_in_progress == atomic_conn_2.atomic_in_progress


@pytest.mark.parametrize(argnames='create_conn_plus',
                         argvalues=(make_plus_connection_from, ConnectionPlus),
                         ids=('make_plus_connection_from', 'ConnectionPlus'))
def test_that_use_of_atomic_commits_only_at_outermost_context(
        tmp_path, create_conn_plus):
    """
    This test tests the behavior of `ConnectionPlus` that is created from
    `sqlite3.Connection` with respect to `atomic` context manager and commits.
    """
    dbfile = str(tmp_path / 'temp.db')

    sqlite_conn = connect(dbfile)
    plus_conn = create_conn_plus(sqlite_conn)

    # this connection is going to be used to test whether changes have been
    # committed to the database file
    control_conn = connect(dbfile)

    get_all_runs = 'SELECT * FROM runs'
    insert_run_with_name = 'INSERT INTO runs (name) VALUES (?)'

    # assert that at the beginning of the test there are no runs in the
    # table; we'll be adding new rows to the runs table below

    assert 0 == len(plus_conn.execute(get_all_runs).fetchall())
    assert 0 == len(control_conn.execute(get_all_runs).fetchall())

    # add 1 new row, and assert the state of the runs table at every step
    # note that control_conn will only detect the change after the `atomic`
    # context manager is exited

    with atomic(plus_conn) as atomic_conn:

        assert 0 == len(plus_conn.execute(get_all_runs).fetchall())
        assert 0 == len(atomic_conn.execute(get_all_runs).fetchall())
        assert 0 == len(control_conn.execute(get_all_runs).fetchall())

        atomic_conn.cursor().execute(insert_run_with_name, ['aaa'])

        assert 1 == len(plus_conn.execute(get_all_runs).fetchall())
        assert 1 == len(atomic_conn.execute(get_all_runs).fetchall())
        assert 0 == len(control_conn.execute(get_all_runs).fetchall())

    assert 1 == len(plus_conn.execute(get_all_runs).fetchall())
    assert 1 == len(atomic_conn.execute(get_all_runs).fetchall())
    assert 1 == len(control_conn.execute(get_all_runs).fetchall())

    # let's add two new rows but each inside its own `atomic` context manager
    # we expect to see the actual change in the database only after we exit
    # the outermost context.

    with atomic(plus_conn) as atomic_conn_1:

        assert 1 == len(plus_conn.execute(get_all_runs).fetchall())
        assert 1 == len(atomic_conn_1.execute(get_all_runs).fetchall())
        assert 1 == len(control_conn.execute(get_all_runs).fetchall())

        atomic_conn_1.cursor().execute(insert_run_with_name, ['bbb'])

        assert 2 == len(plus_conn.execute(get_all_runs).fetchall())
        assert 2 == len(atomic_conn_1.execute(get_all_runs).fetchall())
        assert 1 == len(control_conn.execute(get_all_runs).fetchall())

        with atomic(atomic_conn_1) as atomic_conn_2:

            assert 2 == len(plus_conn.execute(get_all_runs).fetchall())
            assert 2 == len(atomic_conn_1.execute(get_all_runs).fetchall())
            assert 2 == len(atomic_conn_2.execute(get_all_runs).fetchall())
            assert 1 == len(control_conn.execute(get_all_runs).fetchall())

            atomic_conn_2.cursor().execute(insert_run_with_name, ['ccc'])

            assert 3 == len(plus_conn.execute(get_all_runs).fetchall())
            assert 3 == len(atomic_conn_1.execute(get_all_runs).fetchall())
            assert 3 == len(atomic_conn_2.execute(get_all_runs).fetchall())
            assert 1 == len(control_conn.execute(get_all_runs).fetchall())

        assert 3 == len(plus_conn.execute(get_all_runs).fetchall())
        assert 3 == len(atomic_conn_1.execute(get_all_runs).fetchall())
        assert 3 == len(atomic_conn_2.execute(get_all_runs).fetchall())
        assert 1 == len(control_conn.execute(get_all_runs).fetchall())

    assert 3 == len(plus_conn.execute(get_all_runs).fetchall())
    assert 3 == len(atomic_conn_1.execute(get_all_runs).fetchall())
    assert 3 == len(atomic_conn_2.execute(get_all_runs).fetchall())
    assert 3 == len(control_conn.execute(get_all_runs).fetchall())
