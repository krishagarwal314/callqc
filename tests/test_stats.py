from callqc.stats import bootstrap_ci, bootstrap_diff_ci, fisher_p, holm, permutation_p


def test_bootstrap_ci_brackets_mean():
    m, lo, hi = bootstrap_ci([0, 1] * 50)
    assert lo < m == 0.5 < hi


def test_noise_is_not_significant():
    a = [0, 1, 0, 0, 1, 0, 1, 0, 0, 1] * 3
    b = [1, 0, 0, 1, 0, 0, 1, 0, 1, 0] * 3
    assert fisher_p(sum(a), len(a), sum(b), len(b)) > 0.5
    assert permutation_p(a, b, n_perm=999) > 0.5
    d, lo, hi = bootstrap_diff_ci(a, b)
    assert lo < 0 < hi


def test_real_lift_is_significant():
    assert fisher_p(5, 100, 30, 100) < 0.001


def test_holm_monotone_and_capped():
    adj = holm([0.01, 0.04, 0.03])
    assert adj[0] == 0.03 and max(adj) <= 1 and adj[1] >= adj[2]
