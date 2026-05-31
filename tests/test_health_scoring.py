from shared.health_scoring import compute_security_posture_component


def test_security_posture_full_score_when_all_good():
    result = compute_security_posture_component(
        mfa_enabled_users=10,
        mfa_total_users=10,
        exposed_vm_count=0,
        stale_vm_count=0,
        total_vm_count=20,
    )
    assert result["score"] == 15


def test_security_posture_penalizes_exposure_and_stale_images():
    result = compute_security_posture_component(
        mfa_enabled_users=2,
        mfa_total_users=10,
        exposed_vm_count=4,
        stale_vm_count=6,
        total_vm_count=10,
    )
    assert result["score"] < 15
    assert result["details"]["subscores"]["mfa_coverage"] <= 1
    assert result["details"]["subscores"]["exposed_ports"] == 2
    assert result["details"]["subscores"]["os_recency"] == 0
