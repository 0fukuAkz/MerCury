"""Tests for rotation.py coverage."""

from mercury.features.rotation import RotationManager, RotationStrategy

def test_rotation_basic_strategies():
    mgr = RotationManager()
    mgr.register("sub", ["S1", "S2"], strategy=RotationStrategy.ROUND_ROBIN)
    
    assert mgr.get_next("sub") == "S1"
    assert mgr.get_next("sub") == "S2"
    assert mgr.get_next("sub") == "S1"
    
    mgr.register("rand", ["R1"], strategy=RotationStrategy.RANDOM)
    assert mgr.get_next("rand") == "R1"

def test_rotation_weighted():
    mgr = RotationManager()
    mgr.register("weight", ["W1", "W2"], strategy=RotationStrategy.WEIGHTED, weights=[0.9, 0.1])
    
    # Rough check
    results = [mgr.get_next("weight") for _ in range(10)]
    assert "W1" in results

def test_rotation_sequential():
    mgr = RotationManager()
    mgr.register("seq", ["A", "B"], strategy=RotationStrategy.SEQUENTIAL)
    
    assert mgr.get_next("seq") == "A"
    assert mgr.get_next("seq") == "A" # Doesn't advance automatically
    
    mgr.advance("seq")
    assert mgr.get_next("seq") == "B"

def test_rotation_enable_disable():
    mgr = RotationManager()
    mgr.register("ed", ["X", "Y"])
    mgr.disable_item("ed", 0) # X disabled
    
    assert mgr.get_next("ed") == "Y"
    mgr.enable_item("ed", 0)
    # Round robin reset/index might vary but should see X
    assert mgr.get_next("ed") in ["X", "Y"]

def test_rotation_stats_and_reset():
    mgr = RotationManager()
    mgr.register("stat", ["V1"])
    mgr.get_next("stat")
    
    stats = mgr.get_statistics("stat")
    assert stats['item_counts']['V1'] == 1
    
    mgr.reset("stat")
    assert mgr.get_statistics("stat")['item_counts']['V1'] == 0

def test_rotation_from_config():
    config = {
        'test': {
            'items': ['C1', 'C2'],
            'strategy': 'weighted',
            'weights': [0.5, 0.5]
        }
    }
    mgr = RotationManager.from_config(config)
    assert mgr.is_registered('test')
    assert mgr._rotation_sets['test'].strategy == RotationStrategy.WEIGHTED

def test_rotation_edge_cases():
    mgr = RotationManager()
    assert mgr.get_next("nonexistent", default="DEF") == "DEF"
    assert mgr.get_current("nonexistent", default="DEF") == "DEF"
    
    mgr.register("empty", [])
    assert mgr.get_next("empty") is None
