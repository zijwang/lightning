from lightning_app.utilities.replicated_state import ReplicatedState


def test_replicated_state():

    value = {"1": "0"}
    replicated_state = ReplicatedState(4, value)
    assert id(replicated_state[0]) == id(value)
    assert id(replicated_state[1]) != id(value)
    assert replicated_state[1] == value
    assert len(replicated_state) == 4
