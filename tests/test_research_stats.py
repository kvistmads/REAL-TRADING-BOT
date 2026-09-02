"""Tests for research/stats.py.

Statistikken her er håndskrevet (ingen scipy på numpy 2.5), så den holdes op mod
lukkede former og kendte referenceværdier frem for mod sig selv. Fejl i disse
funktioner ville vise sig som en falsk konklusion i confidence-valideringen — ikke
som en exception — og derfor er de dækket tættere end koden omkring dem.
"""
from __future__ import annotations

import math

import numpy as np
import pytest

from research import stats


class TestIncompleteBeta:
    def test_symmetrisk_midtpunkt(self):
        assert stats.regularized_incomplete_beta(1, 1, 0.5) == pytest.approx(0.5)

    def test_kendt_værdi(self):
        # I_0.5(2,3) = 11/16
        assert stats.regularized_incomplete_beta(2, 3, 0.5) == pytest.approx(0.6875)

    def test_randpunkter(self):
        assert stats.regularized_incomplete_beta(2, 3, 0.0) == 0.0
        assert stats.regularized_incomplete_beta(2, 3, 1.0) == 1.0


class TestTFordeling:
    def test_t_nul_giver_p_en(self):
        assert stats.t_test_p_value(0.0, 10) == pytest.approx(1.0)

    def test_kendt_p_værdi(self):
        # t=2.0, df=30 → tosidet p ≈ 0.0546 (standard t-tabel)
        assert stats.t_test_p_value(2.0, 30) == pytest.approx(0.0546, abs=1e-3)

    def test_fortegn_er_ligegyldigt(self):
        assert stats.t_test_p_value(-2.0, 30) == pytest.approx(stats.t_test_p_value(2.0, 30))

    def test_uden_frihedsgrader(self):
        assert stats.t_test_p_value(5.0, 0) == 1.0


class TestPointBiserial:
    def test_matcher_pearson(self):
        x = np.array([1, 2, 3, 4, 5, 6, 7, 8, 9, 10.0])
        y = np.array([0, 0, 1, 0, 1, 1, 0, 1, 1, 1.0])
        assert stats.point_biserial(x, y).r == pytest.approx(np.corrcoef(x, y)[0, 1])

    def test_perfekt_adskillelse(self):
        c = stats.point_biserial([1, 2, 3, 4], [0, 0, 1, 1])
        assert c.r > 0.85 and c.p_value < 0.2

    def test_negativt_fortegn_fanges(self):
        """Et led kan pege den forkerte vej — det skal kunne ses, ikke skjules."""
        assert stats.point_biserial([1, 2, 3, 4], [1, 1, 0, 0]).r < 0

    def test_konstant_serie_er_udefineret(self):
        assert math.isnan(stats.point_biserial([1, 1, 1, 1], [0, 1, 0, 1]).r)

    def test_nan_udelades_fra_n(self):
        assert stats.point_biserial([1, 2, 3, float("nan")], [0, 0, 1, 1]).n == 3

    def test_for_få_punkter(self):
        assert math.isnan(stats.point_biserial([1, 2], [0, 1]).r)


class TestSpearman:
    def test_lukket_form(self):
        a = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
        b = [2, 1, 4, 3, 6, 5, 8, 7, 10, 9]
        d2 = sum((x - y) ** 2 for x, y in zip(a, b))
        expected = 1 - 6 * d2 / (10 * (10 ** 2 - 1))
        assert stats.spearman(a, b).r == pytest.approx(expected)

    def test_monoton_men_ikke_lineær(self):
        """Rang-korrelationen er 1 for enhver monoton sammenhæng."""
        x = [1, 2, 3, 4, 5]
        assert stats.spearman(x, [1, 4, 9, 16, 25]).r == pytest.approx(1.0)

    def test_bindinger_får_gennemsnitsrang(self):
        r = stats.spearman([1, 1, 2, 2, 3], [1, 2, 2, 3, 3])
        manual = np.corrcoef([1.5, 1.5, 3.5, 3.5, 5.0], [1, 2.5, 2.5, 4.5, 4.5])[0, 1]
        assert r.r == pytest.approx(manual)


class TestAndele:
    def test_wilson_symmetrisk_om_en_halv(self):
        low, high = stats.wilson_interval(50, 100)
        assert low + high == pytest.approx(1.0)
        assert low == pytest.approx(0.404, abs=1e-3)

    def test_wilson_holder_sig_i_intervallet(self):
        """Wald ville give (0, 0) her; Wilson giver en ærlig øvre grænse."""
        low, high = stats.wilson_interval(0, 10)
        assert low == 0.0
        assert 0.0 < high < 0.35

    def test_wilson_uden_data(self):
        assert stats.wilson_interval(0, 0) == (0.0, 1.0)

    def test_diff_interval_indeholder_estimatet(self):
        low, high = stats.proportion_diff_interval(60, 150, 45, 150)
        assert low < (60 / 150 - 45 / 150) < high

    def test_diff_interval_bliver_smallere_med_flere_handler(self):
        smal = stats.proportion_diff_interval(600, 1500, 450, 1500)
        bred = stats.proportion_diff_interval(60, 150, 45, 150)
        assert (smal[1] - smal[0]) < (bred[1] - bred[0])

    def test_diff_interval_uden_data(self):
        assert stats.proportion_diff_interval(0, 0, 5, 10) == (-1.0, 1.0)


class TestStyrke:
    def test_matcher_prd_ens_1566_handler(self):
        """PRD'en regner med ~1.566 handler pr. bånd for at se 5 pp — samme formel."""
        assert stats.min_detectable_diff(1566) == pytest.approx(0.05, abs=0.002)

    def test_stikprøven_vi_har_er_langt_grovere(self):
        assert stats.min_detectable_diff(150) > 0.10

    def test_flere_handler_ser_mindre_forskelle(self):
        assert stats.min_detectable_diff(1000) < stats.min_detectable_diff(100)
