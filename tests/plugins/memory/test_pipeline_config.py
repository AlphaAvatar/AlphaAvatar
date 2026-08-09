import pytest

from alphaavatar.plugins.memory.pipeline import MaintenanceOp, MemoryPipelineConfig


def test_ops_parsed_from_strings():
    cfg = MemoryPipelineConfig(maintenance={"ops": ["add", "noop", "update"]})
    assert cfg.maintenance.ops == [
        MaintenanceOp.ADD,
        MaintenanceOp.NOOP,
        MaintenanceOp.UPDATE,
    ]
    assert cfg.maintenance.uses_llm is True
    assert cfg.maintenance.allow_update is True


def test_ops_must_contain_add():
    with pytest.raises(ValueError, match="must contain 'add'"):
        MemoryPipelineConfig(maintenance={"ops": ["noop"]})


def test_update_requires_noop():
    with pytest.raises(ValueError, match="requires 'noop'"):
        MemoryPipelineConfig(maintenance={"ops": ["add", "update"]})


def test_unimplemented_values_raise_rather_than_degrade():
    with pytest.raises(ValueError, match="not implemented"):
        MemoryPipelineConfig(key={"organization": "merge_by_type"})
    with pytest.raises(ValueError, match="not implemented"):
        MemoryPipelineConfig(value={"source": "session"})
