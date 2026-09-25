import pytest
from pydantic import ValidationError

from contextrail.models import Subject


def anil(**kw):
    base = {"source": "hris", "source_id": "E-1042", "display_name": "Anil Kumar", "employment_type": "employee",
            "role": "payments-engineer", "team": "payments"}
    return Subject(**(base | kw))


# --- Subject (T043) ----------------------------------------------------------------------------------------

def test_subject_requires_an_id_not_a_name():
    assert anil().source_id == "E-1042"
    with pytest.raises(ValidationError, match="not a name"):
        anil(source_id="Anil Kumar")
    with pytest.raises(ValidationError):
        anil(source_id="")


def test_subject_rejects_unknown_fields_and_types():
    with pytest.raises(ValidationError):
        anil(employment_type="intern")
    with pytest.raises(ValidationError):
        anil(salary=100)  # extra fields forbidden: capsules carry allow-listed fields only (§16)


def test_contractor_carries_sow_repos():
    priya = anil(source_id="W-8841", display_name="Priya Sharma", employment_type="contractor",
                 sow_repos=["northbeam/perception-sdk"])
    assert priya.sow_repos == ["northbeam/perception-sdk"]
