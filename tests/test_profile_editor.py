import json
import re

import pytest
from fastapi.testclient import TestClient

from pandapply.profiles import add_profile, list_profiles
from pandapply.storage import connect, migrate
from pandapply.web import create_app


@pytest.fixture
def editor(tmp_path):
    path = tmp_path / 'data.db'
    migrate(path)
    with connect(path) as db:
        profile = add_profile(db, 'Backend', 'UTC', {
            'role_queries': ['Backend'], 'locations': ['Colombia'],
            'languages': ['es', 'en'], 'custom_filter': {'level': 2}})
    client = TestClient(create_app(path, 'secret'), base_url='http://localhost')
    client.auth = ('pandapply', 'secret')
    page = client.get(f'/?view=perfiles&profile={profile}')
    csrf = re.search(r"name='csrf' value='([^']+)'", page.text).group(1)
    return path, client, profile, {'csrf': csrf, 'version': '1', 'name': 'Fullstack <senior>',
                                 'skills': 'Python, SQL', 'locations': 'Bogotá, Medellín',
                                 'languages': 'es, en', 'work_modes': ['remote', 'hybrid'],
                                 'salary': '3500', 'nice_to_have_skills': 'Docker',
                                 'seniority': 'Senior', 'min_verified_years': '4.5',
                                 'excluded_companies': 'Empresa A', 'excluded_keywords': 'guardias',
                                 'required_keywords': 'Python', 'contract_types': 'indefinido',
                                 'english_level': 'B2', 'cv_directory': 'C:/CV propios',
                                 'cv_language': 'es', 'preferred_cvs': 'cv-backend',
                                 'timezones': 'America/Bogota'}


def test_edit_all_fields_is_persisted_and_keeps_unknown_preferences(editor):
    path, client, profile, form = editor
    response = client.post(f'/profiles/{profile}/edit', data=form,
                           headers={'Origin': 'http://localhost'}, follow_redirects=False)
    assert response.status_code == 303
    with connect(path) as db:
        saved = list_profiles(db)[0]
        assert saved['name'] == form['name'] and saved['version'] == 2
        prefs = saved['preferences']
        assert prefs['role_queries'] == [form['name']]
        assert prefs['work_mode'] == ['remote', 'hybrid']
        assert prefs['locations'] == ['Bogotá', 'Medellín']
        assert prefs['languages'] == ['es', 'en']
        assert prefs['salary_min_usd_month'] == 3500
        assert prefs['min_verified_years'] == 4.5
        assert prefs['custom_filter'] == {'level': 2}
        assert prefs['cv_directory'] == 'C:/CV propios'
        assert prefs['nice_to_have_skills'] == ['Docker']
        assert prefs['seniority'] == 'Senior' and prefs['english_level'] == 'B2'
        assert prefs['required_keywords'] == ['Python'] and prefs['excluded_keywords'] == ['guardias']
        assert prefs['excluded_companies'] == ['Empresa A']
        assert prefs['contract_types'] == ['indefinido']
        assert prefs['cv_language'] == 'es' and prefs['preferred_cvs'] == ['cv-backend']
        assert prefs['timezones'] == ['America/Bogota']
        assert db.execute('SELECT count(*) FROM knowledge_claims').fetchone()[0] == 0
    page = client.get(response.headers['location'])
    assert 'Fullstack &lt;senior&gt;' in page.text and 'value=\'Bogotá, Medellín\'' in page.text
    assert client.post(f'/profiles/{profile}/edit', data=form,
                       headers={'Origin': 'http://localhost'}).status_code == 409


def test_custom_queries_and_advanced_fields_can_be_edited_or_cleared(editor):
    path, client, profile, form = editor
    form.update(role_queries='Platform Engineer, Backend Python', skills='', salary='',
                extra_preferences=json.dumps({'custom_filter': {'level': 3}}))
    assert client.post(f'/profiles/{profile}/edit', data=form,
                       headers={'Origin': 'http://localhost'}, follow_redirects=False).status_code == 303
    with connect(path) as db:
        prefs = list_profiles(db)[0]['preferences']
        assert prefs['role_queries'] == ['Platform Engineer', 'Backend Python']
        assert prefs['must_have_skills'] == [] and 'salary_min_usd_month' not in prefs
        assert prefs['custom_filter'] == {'level': 3}


@pytest.mark.parametrize('changes', [{'name': ' '}, {'salary': '-1'}, {'salary': 'nan'},
                                    {'min_verified_years': '-2'}, {'work_modes': ['bogus']},
                                    {'extra_preferences': '[]'}, {'extra_preferences': '{bad'},
                                    {'extra_preferences': '{"work_mode": "onsite"}'}])
def test_invalid_edits_do_not_save_partial_changes(editor, changes):
    path, client, profile, form = editor
    result = client.post(f'/profiles/{profile}/edit', data={**form, **changes},
                         headers={'Origin': 'http://localhost'})
    assert result.status_code == 400 and 'text/html' in result.headers['content-type']
    assert 'No se guardaron los cambios' in result.text
    with connect(path) as db:
        assert list_profiles(db)[0]['name'] == 'Backend' and list_profiles(db)[0]['version'] == 1


def test_editor_requires_session_origin_and_csrf(editor):
    _, client, profile, form = editor
    route = f'/profiles/{profile}/edit'
    assert client.post(route, data=form).status_code == 403
    assert client.post(route, data=form, headers={'Origin': 'https://evil.test'}).status_code == 403
    assert client.post(route, data={**form, 'csrf': 'bad'},
                       headers={'Origin': 'http://localhost'}).status_code == 403
    client.auth = None
    assert client.post(route, data=form, headers={'Origin': 'http://localhost'}).status_code == 401


def test_clearing_modes_and_optional_fields_removes_restrictions(editor):
    path, client, profile, form = editor
    form.pop('work_modes')
    form.update(work_modes_present='1', salary='', min_verified_years='', seniority='',
                locations='', languages='', excluded_companies='')
    assert client.post(f'/profiles/{profile}/edit', data=form,
                       headers={'Origin': 'http://localhost'}, follow_redirects=False).status_code == 303
    with connect(path) as db:
        prefs = list_profiles(db)[0]['preferences']
        assert 'work_mode' not in prefs and 'salary_min_usd_month' not in prefs
        assert 'min_verified_years' not in prefs and 'seniority' not in prefs
        assert prefs['locations'] == [] and prefs['languages'] == [] and prefs['excluded_companies'] == []
