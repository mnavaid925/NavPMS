"""Unit tests for `_save_answer_from_post` — the per-type answer parser in the
vendor portal (previously the largest untested surface, §7 of the SQA report),
including the D-04 upload-extension reject on vendor answer files.
"""
from datetime import date
from decimal import Decimal

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.http import QueryDict
from django.utils.datastructures import MultiValueDict

from apps.rfx.forms import MAX_ANSWER_FILE_BYTES
from apps.rfx.models import RfxAnswer, RfxQuestion
from apps.rfx.portal_views import _save_answer_from_post

pytestmark = pytest.mark.django_db


def _q(section, qtype, **kw):
    return RfxQuestion.all_objects.create(
        tenant=section.tenant, section=section, position=kw.pop('position', 1),
        prompt=kw.pop('prompt', 'Q'), question_type=qtype, **kw,
    )


def _post(question, **vals):
    qd = QueryDict(mutable=True)
    for suffix, value in vals.items():
        key = f'answer_{question.pk}_{suffix}'
        if isinstance(value, list):
            qd.setlist(key, value)
        else:
            qd[key] = value
    return qd


def _call(question, post=None, files=None):
    answer = RfxAnswer(question=question)
    err = _save_answer_from_post(
        answer, question, post or QueryDict(), files or MultiValueDict(),
    )
    return answer, err


# ---------- text / longtext / yes_no ----------

def test_text_answer(section):
    q = _q(section, 'text')
    answer, err = _call(q, _post(q, text='  hello  '))
    assert err == '' and answer.value_text == 'hello'


def test_yes_no_valid(section):
    q = _q(section, 'yes_no')
    answer, err = _call(q, _post(q, text='YES'))
    assert err == '' and answer.value_text == 'yes'


def test_yes_no_invalid(section):
    q = _q(section, 'yes_no')
    answer, err = _call(q, _post(q, text='maybe'))
    assert 'Yes or No' in err


# ---------- number / scale ----------

def test_number_valid(section):
    q = _q(section, 'number')
    answer, err = _call(q, _post(q, number='42.5'))
    assert err == '' and answer.value_number == Decimal('42.5')


def test_number_invalid(section):
    q = _q(section, 'number')
    _, err = _call(q, _post(q, number='abc'))
    assert 'not a number' in err


def test_scale_in_range(section):
    q = _q(section, 'scale', max_score=5)
    answer, err = _call(q, _post(q, number='3'))
    assert err == '' and answer.value_number == Decimal('3')


def test_scale_out_of_range(section):
    q = _q(section, 'scale', max_score=5)
    _, err = _call(q, _post(q, number='9'))
    assert 'between 0 and 5' in err


# ---------- date ----------

def test_date_valid(section):
    q = _q(section, 'date')
    answer, err = _call(q, _post(q, date='2026-01-15'))
    assert err == '' and answer.value_date == date(2026, 1, 15)


def test_date_invalid(section):
    q = _q(section, 'date')
    _, err = _call(q, _post(q, date='15-01-2026'))
    assert 'invalid date' in err


# ---------- choices ----------

def test_single_choice_keeps_one(section):
    q = _q(section, 'single_choice', choices=['A', 'B', 'C'])
    answer, err = _call(q, _post(q, choices=['B', 'C']))
    assert err == '' and answer.value_choices == ['B']  # truncated to one


def test_choice_drops_undeclared_option(section):
    q = _q(section, 'multi_choice', choices=['A', 'B'])
    answer, err = _call(q, _post(q, choices=['A', 'Z']))
    assert err == '' and answer.value_choices == ['A']  # 'Z' is not a declared option


# ---------- file (D-04) ----------

def test_file_allowed_extension(section):
    q = _q(section, 'file')
    f = SimpleUploadedFile('spec.pdf', b'small', content_type='application/pdf')
    answer, err = _call(q, files=MultiValueDict({f'answer_{q.pk}_file': [f]}))
    # bool(FieldFile) is False when no file is stored; `is not None` would be a
    # vacuous assertion (a fresh FieldFile is <FieldFile: None>, not None).
    assert err == '' and bool(answer.value_file)


def test_file_rejects_disallowed_extension(section):
    q = _q(section, 'file')
    f = SimpleUploadedFile('evil.svg', b'<svg onload=alert(1)>',
                           content_type='image/svg+xml')
    _, err = _call(q, files=MultiValueDict({f'answer_{q.pk}_file': [f]}))
    assert 'not allowed' in err


def test_file_rejects_oversize(section):
    q = _q(section, 'file')
    big = SimpleUploadedFile('big.pdf', b'A' * (MAX_ANSWER_FILE_BYTES + 1),
                             content_type='application/pdf')
    _, err = _call(q, files=MultiValueDict({f'answer_{q.pk}_file': [big]}))
    assert 'MB or less' in err
