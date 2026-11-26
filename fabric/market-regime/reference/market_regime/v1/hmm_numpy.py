"""Gaussian HMM (diagonal covariance) implemented with numpy only.

Why not hmmlearn: Fabric pipeline runs cannot rely on inline %pip installs, and the
regime model only needs a small, auditable EM. Missing values are handled per feature:
with a diagonal covariance a NaN dimension is simply left out of the likelihood and of
the mean/variance updates. A row with every feature missing has likelihood 1, so the
state only propagates through the transition matrix.

Probabilities returned by `filter_proba` at row t use rows 0..t only (forward
filtering), so they contain no look-ahead.
"""
from __future__ import annotations

import numpy as np

LOG_2PI = float(np.log(2.0 * np.pi))


class GaussianHMMDiag:
    def __init__(self, n_states=3, n_iter=150, tol=1e-4, min_var=1e-3,
                 transmat_prior=10.0, random_state=0):
        self.n_states = int(n_states)
        self.n_iter = int(n_iter)
        self.tol = float(tol)
        self.min_var = float(min_var)
        # Dirichlet pseudo-counts added to the diagonal of the transition counts.
        # Encourages persistent regimes (markets stay in a regime for weeks).
        self.transmat_prior = float(transmat_prior)
        self.random_state = random_state
        self.startprob_ = None
        self.transmat_ = None
        self.means_ = None
        self.vars_ = None
        self.loglik_ = -np.inf
        self.n_iter_done_ = 0

    # ------------------------------------------------------------------ utils
    @staticmethod
    def _mask(X):
        """Element-wise observation mask (T, d)."""
        return np.isfinite(X)

    def _log_emission(self, X, mask):
        Xz = np.where(mask, X, 0.0)
        var = self.vars_
        m = mask[:, None, :].astype(float)
        term = (np.log(var)[None, :, :] + LOG_2PI
                + (Xz[:, None, :] - self.means_[None, :, :]) ** 2 / var[None, :, :])
        return -0.5 * np.sum(term * m, axis=2)

    def _forward(self, logB):
        T, K = logB.shape
        rowmax = logB.max(axis=1)
        B = np.exp(logB - rowmax[:, None])
        A = self.transmat_
        alpha = np.empty((T, K))
        c = np.empty(T)
        a = self.startprob_ * B[0]
        c[0] = a.sum()
        alpha[0] = a / c[0]
        for t in range(1, T):
            a = (alpha[t - 1] @ A) * B[t]
            s = a.sum()
            if not np.isfinite(s) or s <= 0:
                a = np.full(K, 1.0 / K)
                s = 1e-300
            c[t] = s
            alpha[t] = a / s
        loglik = float(np.sum(np.log(c)) + np.sum(rowmax))
        return alpha, c, B, loglik

    def _backward(self, B, c):
        T, K = B.shape
        A = self.transmat_
        beta = np.empty((T, K))
        beta[-1] = 1.0
        for t in range(T - 2, -1, -1):
            beta[t] = (A @ (B[t + 1] * beta[t + 1])) / c[t + 1]
        return beta

    # ------------------------------------------------------------------- init
    def _init_params(self, X, mask, rng, init_params=None):
        K, d = self.n_states, X.shape[1]
        Xo = X[mask.all(axis=1)]
        if init_params is not None:
            self.startprob_ = np.array(init_params["startprob"], dtype=float)
            self.transmat_ = np.array(init_params["transmat"], dtype=float)
            self.means_ = np.array(init_params["means"], dtype=float)
            self.vars_ = np.maximum(np.array(init_params["vars"], dtype=float), self.min_var)
            return
        # k-means++ style seeding on observed rows
        idx = [rng.integers(len(Xo))]
        for _ in range(1, K):
            d2 = np.min(((Xo[:, None, :] - Xo[idx][None, :, :]) ** 2).sum(axis=2), axis=1)
            p = d2 / d2.sum() if d2.sum() > 0 else None
            idx.append(rng.choice(len(Xo), p=p))
        self.means_ = Xo[idx].copy() + rng.normal(0, 0.05, size=(K, d))
        self.vars_ = np.tile(np.maximum(Xo.var(axis=0), self.min_var), (K, 1))
        self.startprob_ = np.full(K, 1.0 / K)
        A = np.full((K, K), 0.05 / max(K - 1, 1))
        np.fill_diagonal(A, 0.95)
        self.transmat_ = A

    # -------------------------------------------------------------------- fit
    def _fit_once(self, X, mask, rng, init_params=None):
        self._init_params(X, mask, rng, init_params)
        K = self.n_states
        prev = -np.inf
        Xz = np.where(mask, X, 0.0)
        mf = mask.astype(float)
        for it in range(self.n_iter):
            logB = self._log_emission(X, mask)
            alpha, c, B, ll = self._forward(logB)
            beta = self._backward(B, c)
            gamma = alpha * beta
            gamma /= gamma.sum(axis=1, keepdims=True)
            xi = self.transmat_ * (alpha[:-1].T @ (B[1:] * beta[1:] / c[1:, None]))
            # M-step
            self.startprob_ = np.clip(gamma[0], 1e-6, None)
            self.startprob_ /= self.startprob_.sum()
            counts = xi + np.eye(K) * self.transmat_prior
            self.transmat_ = counts / counts.sum(axis=1, keepdims=True)
            w = gamma.T @ mf                      # (K, d) observed weight per state & feature
            w = np.where(w <= 1e-10, 1e-10, w)
            self.means_ = (gamma.T @ (Xz * mf)) / w
            diff2 = (Xz[:, None, :] - self.means_[None, :, :]) ** 2 * mf[:, None, :]
            self.vars_ = np.maximum(np.einsum("tk,tkd->kd", gamma, diff2) / w, self.min_var)
            self.n_iter_done_ = it + 1
            if np.isfinite(prev) and abs(ll - prev) <= self.tol * max(1.0, abs(prev)):
                prev = ll
                break
            prev = ll
        self.loglik_ = self.score(X)
        return self

    def fit(self, X, n_init=4, warm_start=None):
        """Fit with several random restarts (+ optional warm start). Keeps the best log-likelihood."""
        X = np.asarray(X, dtype=float)
        mask = self._mask(X)
        if mask.all(axis=1).sum() < self.n_states * 20:
            raise ValueError("HMM_TOO_FEW_OBSERVED_ROWS")
        rng = np.random.default_rng(self.random_state)
        best = None
        trials = []
        if warm_start is not None:
            trials.append(warm_start)
        trials += [None] * max(int(n_init), 1)
        for init in trials:
            cand = GaussianHMMDiag(self.n_states, self.n_iter, self.tol, self.min_var,
                                   self.transmat_prior, self.random_state)
            try:
                cand._fit_once(X, mask, rng, init)
            except FloatingPointError:
                continue
            if np.isfinite(cand.loglik_) and (best is None or cand.loglik_ > best.loglik_):
                best = cand
        if best is None:
            raise RuntimeError("HMM_FIT_FAILED")
        self.__dict__.update(best.__dict__)
        return self

    # --------------------------------------------------------------- inference
    def score(self, X):
        X = np.asarray(X, dtype=float)
        mask = self._mask(X)
        return self._forward(self._log_emission(X, mask))[3]

    def filter_proba(self, X):
        """P(state_t | x_0..x_t) for every t (no look-ahead)."""
        X = np.asarray(X, dtype=float)
        mask = self._mask(X)
        return self._forward(self._log_emission(X, mask))[0]

    def smooth_proba(self, X):
        """P(state_t | x_0..x_T) — uses future rows; for reference/diagnostics only."""
        X = np.asarray(X, dtype=float)
        mask = self._mask(X)
        alpha, c, B, _ = self._forward(self._log_emission(X, mask))
        beta = self._backward(B, c)
        g = alpha * beta
        return g / g.sum(axis=1, keepdims=True)

    def n_parameters(self, n_features):
        K = self.n_states
        return (K - 1) + K * (K - 1) + 2 * K * n_features

    def bic(self, X):
        X = np.asarray(X, dtype=float)
        n_obs = int(self._mask(X).any(axis=1).sum())
        return -2.0 * self.score(X) + self.n_parameters(X.shape[1]) * np.log(max(n_obs, 2))

    def get_params(self):
        return {"startprob": self.startprob_.tolist(), "transmat": self.transmat_.tolist(),
                "means": self.means_.tolist(), "vars": self.vars_.tolist()}

    def permuted(self, order):
        """Return a copy whose state index i equals old state order[i]."""
        order = np.asarray(order)
        m = GaussianHMMDiag(self.n_states, self.n_iter, self.tol, self.min_var,
                            self.transmat_prior, self.random_state)
        m.startprob_ = self.startprob_[order]
        m.transmat_ = self.transmat_[np.ix_(order, order)]
        m.means_ = self.means_[order]
        m.vars_ = self.vars_[order]
        m.loglik_ = self.loglik_
        m.n_iter_done_ = self.n_iter_done_
        return m
