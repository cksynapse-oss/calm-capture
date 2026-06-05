"""
active_inference_agent.py — CorteonAgent: a pymdp-based Active Inference agent
for Calm Capture knowledge resurfacing decisions.

State-space
-----------
Factor 0 — Topic Context         : K=8 states (dynamic clusters 0-7)
Factor 1 — Information Need      : 4 states  {Seeking=0, Processing=1, Synthesizing=2, Idle=3}
Factor 2 — Familiarity           : 3 states  {Novice=0, Intermediate=1, Expert=2}

Total hidden states: 8 × 4 × 3 = 96

Observation modalities
-----------------------
O[0] — Active Context  : 9 levels (0=unrecognised, 1-8=topic cluster id)
O[1] — Capture Activity: 4 levels {none=0, same_topic=1, new_topic=2, strong_note=3}
O[2] — Temporal Signal : 3 levels {recent=0, moderate=1, stale=2}
O[3] — UI Feedback     : 4 levels {no_overlay=0, clicked=1, dismissed=2, ignored=3}

Control factors
---------------
C[0] — Resurface Decision : 4 actions {nothing=0, top_match=1, high_PE=2, suggest_connection=3}
C[1] — Display Intensity  : 3 actions {peripheral=0, standard=1, expanded=2}
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Model dimensions
# ---------------------------------------------------------------------------

NUM_TOPICS = 8          # Factor 0 (Topic Context)
NUM_NEEDS = 4           # Factor 1 (Information Need)
NUM_FAMILIARITY = 3     # Factor 2 (Familiarity)

NUM_CONTEXT_OBS = NUM_TOPICS + 1   # 9  (0 = unrecognised)
NUM_CAPTURE_OBS = 4
NUM_TEMPORAL_OBS = 3
NUM_FEEDBACK_OBS = 4

NUM_RESURFACE_ACTIONS = 4
NUM_DISPLAY_ACTIONS = 3

# Factor sizes
NUM_STATES = [NUM_TOPICS, NUM_NEEDS, NUM_FAMILIARITY]
NUM_OBS    = [NUM_CONTEXT_OBS, NUM_CAPTURE_OBS, NUM_TEMPORAL_OBS, NUM_FEEDBACK_OBS]
NUM_CONTROLS = [NUM_RESURFACE_ACTIONS, NUM_DISPLAY_ACTIONS]

# Precision on policies
ALPHA = 8.0


# ---------------------------------------------------------------------------
# Matrix builders
# ---------------------------------------------------------------------------

def _build_A() -> list:
    """
    Build A-matrices (likelihood / observation models).

    Each A[m] has shape (num_obs_m, *num_states).
    We use Trairūpya (triple-characteristic) sparsity:
      — Vyāpti  : each hidden state maps to at most one observation level
      — Pakṣa   : the mapping is highly concentrated (diagonal dominance)
      — Sapakṣa : off-diagonal mass is small and uniform
    """
    # ------------------------------------------------------------------
    # A[0] — Active Context modality
    # shape: (9, 8, 4, 3)
    # Topic Factor (0) has direct Vyāpti correspondence with context obs.
    # Factor 1 & 2 are marginally uniform (not observed via this modality).
    # ------------------------------------------------------------------
    A0 = np.zeros((NUM_CONTEXT_OBS, NUM_TOPICS, NUM_NEEDS, NUM_FAMILIARITY))
    diag_mass = 0.80
    off_mass  = (1.0 - diag_mass) / (NUM_CONTEXT_OBS - 1)  # ≈ 0.025 per off-diag slot
    for t in range(NUM_TOPICS):
        for n in range(NUM_NEEDS):
            for f in range(NUM_FAMILIARITY):
                A0[:, t, n, f] = off_mass
                A0[t + 1, t, n, f] = diag_mass  # obs index t+1 (1-indexed; 0=unrecognised)
    # When all factors are uncertain (unrecognised context), obs=0 is most probable
    # handled gracefully because softmax over beliefs spreads probability.

    # ------------------------------------------------------------------
    # A[1] — Capture Activity modality
    # shape: (4, 8, 4, 3)
    # Capture activity is driven primarily by Information Need (Factor 1).
    # ------------------------------------------------------------------
    A1 = np.zeros((NUM_CAPTURE_OBS, NUM_TOPICS, NUM_NEEDS, NUM_FAMILIARITY))
    # Mapping Need → most-likely capture observation:
    # Seeking(0)→new_topic(2), Processing(1)→same_topic(1),
    # Synthesizing(2)→strong_note(3), Idle(3)→none(0)
    need_to_cap_obs = {0: 2, 1: 1, 2: 3, 3: 0}
    cap_diag = 0.70
    for t in range(NUM_TOPICS):
        for n in range(NUM_NEEDS):
            for f in range(NUM_FAMILIARITY):
                obs_idx = need_to_cap_obs[n]
                off = (1.0 - cap_diag) / (NUM_CAPTURE_OBS - 1)
                A1[:, t, n, f] = off
                A1[obs_idx, t, n, f] = cap_diag

    # ------------------------------------------------------------------
    # A[2] — Temporal Signal modality
    # shape: (3, 8, 4, 3)
    # Temporal signal is weakly modulated by familiarity;
    # mostly driven by an independent timing process — treated as nearly uniform.
    # ------------------------------------------------------------------
    A2 = np.ones((NUM_TEMPORAL_OBS, NUM_TOPICS, NUM_NEEDS, NUM_FAMILIARITY))
    A2 /= NUM_TEMPORAL_OBS  # uniform — the engine supplies the real temporal obs

    # ------------------------------------------------------------------
    # A[3] — UI Feedback modality
    # shape: (4, 8, 4, 3)
    # Feedback depends on Familiarity (Factor 2):
    #   Novice   → higher click probability
    #   Expert   → higher dismiss probability
    # And on Information Need:
    #   Seeking/Processing → more likely to click
    #   Idle → more likely to ignore
    # ------------------------------------------------------------------
    A3 = np.zeros((NUM_FEEDBACK_OBS, NUM_TOPICS, NUM_NEEDS, NUM_FAMILIARITY))
    # Base probabilities per familiarity level [no_overlay, clicked, dismissed, ignored]
    fam_base = {
        0: np.array([0.50, 0.30, 0.10, 0.10]),  # Novice — curious, clicks more
        1: np.array([0.50, 0.20, 0.15, 0.15]),  # Intermediate
        2: np.array([0.50, 0.10, 0.25, 0.15]),  # Expert — dismisses more
    }
    need_mod = {
        0: np.array([0.0, +0.10, -0.05, -0.05]),  # Seeking adds click prob
        1: np.array([0.0, +0.05, -0.03, -0.02]),
        2: np.array([0.0, +0.03, 0.00, -0.03]),
        3: np.array([0.0, -0.05, 0.00, +0.05]),   # Idle — ignore/no_overlay
    }
    for t in range(NUM_TOPICS):
        for n in range(NUM_NEEDS):
            for f in range(NUM_FAMILIARITY):
                probs = fam_base[f] + need_mod[n]
                probs = np.clip(probs, 0.01, 1.0)
                probs /= probs.sum()
                A3[:, t, n, f] = probs

    return [A0, A1, A2, A3]


def _build_B() -> list:
    """
    Build B-matrices (transition models).

    B[f] has shape (num_states_f, num_states_f, num_controls_f)
    where factor f is controlled by control factor c.
    Factor 0 (Topic Context) is controlled by Resurface Decision.
    Factor 1 (Information Need) is controlled by Resurface Decision.
    Factor 2 (Familiarity) is controlled by Display Intensity.

    Vyāpti determinism: we model deterministic action effects with
    small uniform noise to keep matrices full-rank.
    """
    noise = 0.05
    det_mass = 1.0 - noise

    # ------------------------------------------------------------------
    # B[0] — Topic Context transitions: shape (8, 8, 4)
    # Resurface actions have limited direct effect on topic — mostly identity.
    # ------------------------------------------------------------------
    B0 = np.zeros((NUM_TOPICS, NUM_TOPICS, NUM_RESURFACE_ACTIONS))
    uniform_row = noise / NUM_TOPICS
    for a in range(NUM_RESURFACE_ACTIONS):
        for t in range(NUM_TOPICS):
            B0[:, t, a] = uniform_row
            B0[t, t, a] += det_mass  # self-loop dominates
    # Normalize columns
    for a in range(NUM_RESURFACE_ACTIONS):
        for t in range(NUM_TOPICS):
            col_sum = B0[:, t, a].sum()
            if col_sum > 0:
                B0[:, t, a] /= col_sum

    # ------------------------------------------------------------------
    # B[1] — Information Need transitions: shape (4, 4, 4)
    # Resurface actions nudge Information Need state.
    # nothing(0) → identity (natural drift)
    # top_match(1) → push toward Seeking(0) if Idle
    # high_PE(2) → push toward Processing(1)
    # suggest_connection(3) → push toward Synthesizing(2)
    # ------------------------------------------------------------------
    B1 = np.zeros((NUM_NEEDS, NUM_NEEDS, NUM_RESURFACE_ACTIONS))
    for a in range(NUM_RESURFACE_ACTIONS):
        for n in range(NUM_NEEDS):
            B1[:, n, a] = noise / NUM_NEEDS
            B1[n, n, a] += det_mass
    # Action-specific pushes (add deterministic nudge toward target)
    push_target = {1: 0, 2: 1, 3: 2}  # top_match→Seeking, high_PE→Processing, conn→Synth
    for a, target in push_target.items():
        for n in range(NUM_NEEDS):
            if n != target:
                B1[:, n, a] = noise / NUM_NEEDS
                B1[n, n, a] += det_mass * 0.5
                B1[target, n, a] += det_mass * 0.5
    for a in range(NUM_RESURFACE_ACTIONS):
        for n in range(NUM_NEEDS):
            col_sum = B1[:, n, a].sum()
            if col_sum > 0:
                B1[:, n, a] /= col_sum

    # ------------------------------------------------------------------
    # B[2] — Familiarity transitions: shape (3, 3, 3)
    # Display Intensity (3 actions) modulates familiarity growth.
    # peripheral(0) → identity
    # standard(1) → slight upward drift
    # expanded(2) → stronger upward drift (more exposure = more familiarity)
    # ------------------------------------------------------------------
    B2 = np.zeros((NUM_FAMILIARITY, NUM_FAMILIARITY, NUM_DISPLAY_ACTIONS))
    for a in range(NUM_DISPLAY_ACTIONS):
        for f in range(NUM_FAMILIARITY):
            B2[:, f, a] = noise / NUM_FAMILIARITY
            B2[f, f, a] += det_mass
    # Upward drift for standard and expanded display
    drift = {1: 0.15, 2: 0.30}
    for a, d in drift.items():
        for f in range(NUM_FAMILIARITY):
            if f < NUM_FAMILIARITY - 1:
                B2[:, f, a] = noise / NUM_FAMILIARITY
                B2[f, f, a] += det_mass * (1.0 - d)
                B2[f + 1, f, a] += det_mass * d
    for a in range(NUM_DISPLAY_ACTIONS):
        for f in range(NUM_FAMILIARITY):
            col_sum = B2[:, f, a].sum()
            if col_sum > 0:
                B2[:, f, a] /= col_sum

    return [B0, B1, B2]


def _build_C() -> list:
    """
    C-vectors: prior preferences over observations.

    We express preferences over the UI Feedback modality only;
    other modalities are set to zero (no preferred observation).
    """
    C_list = []
    for m, n_obs in enumerate(NUM_OBS):
        C_list.append(np.zeros(n_obs))

    # Feedback modality (index 3): prefer clicks, dislike dismissals
    # [no_overlay=0, clicked=+3, dismissed=-2, ignored=-0.5]
    C_list[3] = np.array([0.0, 3.0, -2.0, -0.5])
    return C_list


def _build_D() -> list:
    """
    D-vectors: prior beliefs over initial hidden states.

    - Topic Context: uniform (we don't know the topic beforehand)
    - Information Need: Idle with prob 0.75 (user is likely idle at start)
    - Familiarity: slight Novice bias
    """
    D_topic = np.ones(NUM_TOPICS) / NUM_TOPICS
    D_need = np.array([0.08, 0.08, 0.09, 0.75])  # Seeking, Processing, Synth, Idle
    D_familiarity = np.array([0.60, 0.30, 0.10])   # Novice, Intermediate, Expert
    return [D_topic, D_need, D_familiarity]


# ---------------------------------------------------------------------------
# Heuristic fallback agent (used when pymdp is unavailable)
# ---------------------------------------------------------------------------

class _HeuristicAgent:
    """
    Simple rule-based fallback that mimics CorteonAgent's interface.

    Triggered when pymdp cannot be imported.
    """

    def __init__(self) -> None:
        self._last_feedback = 0
        self._inferred_topic = 0
        self._consecutive_dismissals = 0
        logger.warning("pymdp unavailable — using HeuristicAgent fallback.")

    def inference_step(self, obs_tuple: Tuple[int, int, int, int]) -> Dict[str, Any]:
        context_obs, capture_obs, temporal_obs, feedback_obs = obs_tuple

        # Update internal state from feedback
        if feedback_obs == 2:   # dismissed
            self._consecutive_dismissals += 1
        else:
            self._consecutive_dismissals = 0

        if feedback_obs == 1:   # clicked
            self._last_feedback = 1

        # Topic inference from context observation
        self._inferred_topic = max(0, context_obs - 1)

        # Resurface decision
        if temporal_obs == 2 and capture_obs > 0:
            resurface_action = 2  # high_PE (stale + active)
        elif capture_obs == 3:
            resurface_action = 3  # suggest_connection (strong note)
        elif temporal_obs <= 1 and self._consecutive_dismissals < 3:
            resurface_action = 1  # top_match
        else:
            resurface_action = 0  # nothing

        # Display intensity
        if resurface_action == 0:
            display_intensity = 0
        elif temporal_obs == 2:
            display_intensity = 2  # expanded for stale
        else:
            display_intensity = 1  # standard

        # Inferred need
        need_map = {0: "Seeking", 1: "Processing", 2: "Synthesizing", 3: "Idle"}
        need_state = 3  # Idle
        if capture_obs == 3:
            need_state = 2  # Synthesizing
        elif capture_obs == 2:
            need_state = 0  # Seeking
        elif capture_obs == 1:
            need_state = 1  # Processing

        return {
            "resurface_action": resurface_action,
            "display_intensity": display_intensity,
            "inferred_topic": self._inferred_topic,
            "inferred_need": need_map[need_state],
            "topic_entropy": 0.0,
        }

    def process_feedback(self, feedback_dict: Dict[str, Any]) -> None:
        pass  # heuristic agent has no belief state to update


# ---------------------------------------------------------------------------
# CorteonAgent
# ---------------------------------------------------------------------------

class CorteonAgent:
    """
    Active Inference agent for Calm Capture resurfacing decisions.

    Uses pymdp (if available) with a 96-state generative model.
    Falls back transparently to :class:`_HeuristicAgent`.
    """

    def __init__(self) -> None:
        self._pymdp_available = False
        self._agent = None
        self._A = None
        self._B = None
        self._C = None
        self._D = None
        self.build_model()

    # ------------------------------------------------------------------
    # Model construction
    # ------------------------------------------------------------------

    def build_model(self) -> None:
        """Attempt to build the pymdp generative model."""
        try:
            import pymdp  # noqa: PLC0415
            from pymdp import Agent  # noqa: PLC0415

            self._A = _build_A()
            self._B = _build_B()
            self._C = _build_C()
            self._D = _build_D()

            self._agent = Agent(
                A=self._A,
                B=self._B,
                C=self._C,
                D=self._D,
                num_controls=NUM_CONTROLS,
                policy_len=1,
                inference_horizon=1,
                use_param_info_gain=False,
                action_selection="stochastic",
                alpha=ALPHA,
            )
            self._pymdp_available = True
            logger.info(
                "CorteonAgent built with pymdp (%d hidden states, %d obs modalities).",
                NUM_TOPICS * NUM_NEEDS * NUM_FAMILIARITY,
                len(NUM_OBS),
            )

        except ImportError:
            logger.warning("pymdp not installed — activating HeuristicAgent fallback.")
            self._agent = _HeuristicAgent()  # type: ignore[assignment]
            self._pymdp_available = False
        except Exception as exc:  # noqa: BLE001
            logger.error("Failed to build pymdp model: %s — using HeuristicAgent.", exc)
            self._agent = _HeuristicAgent()  # type: ignore[assignment]
            self._pymdp_available = False

    # ------------------------------------------------------------------
    # Inference
    # ------------------------------------------------------------------

    def inference_step(self, obs_tuple: Tuple[int, int, int, int]) -> Dict[str, Any]:
        """
        Run one step of active inference given the current observations.

        Parameters
        ----------
        obs_tuple : (context_obs, capture_obs, temporal_obs, feedback_obs)
            Discrete observation indices as described in the module docstring.

        Returns
        -------
        dict with keys:
            resurface_action  : int 0-3
            display_intensity : int 0-2
            inferred_topic    : int 0-7
            inferred_need     : str ("Seeking" | "Processing" | "Synthesizing" | "Idle")
        """
        if not self._pymdp_available:
            return self._agent.inference_step(obs_tuple)  # type: ignore[union-attr]

        try:
            obs_list = list(obs_tuple)
            # Clamp observations to valid range
            obs_list[0] = int(np.clip(obs_list[0], 0, NUM_CONTEXT_OBS - 1))
            obs_list[1] = int(np.clip(obs_list[1], 0, NUM_CAPTURE_OBS - 1))
            obs_list[2] = int(np.clip(obs_list[2], 0, NUM_TEMPORAL_OBS - 1))
            obs_list[3] = int(np.clip(obs_list[3], 0, NUM_FEEDBACK_OBS - 1))

            # State inference (perception)
            qs = self._agent.infer_states(obs_list)

            # Policy inference (action selection)
            q_pi, efe = self._agent.infer_policies()
            action = self._agent.sample_action()

            # Map actions to named fields
            resurface_action  = int(action[0])
            display_intensity = int(action[1])

            # Extract inferred topic from Factor 0 marginal
            inferred_topic = int(np.argmax(qs[0]))

            # Extract inferred need from Factor 1 marginal
            need_labels = ["Seeking", "Processing", "Synthesizing", "Idle"]
            inferred_need = need_labels[int(np.argmax(qs[1]))]

            # Compute belief entropy of the topic context (Factor 0)
            p_topic = qs[0]
            p_topic_safe = p_topic[p_topic > 1e-12]
            entropy = float(-np.sum(p_topic_safe * np.log(p_topic_safe)))

            return {
                "resurface_action": resurface_action,
                "display_intensity": display_intensity,
                "inferred_topic": inferred_topic,
                "inferred_need": inferred_need,
                "topic_entropy": entropy,
            }

        except Exception as exc:  # noqa: BLE001
            logger.error("inference_step failed: %s — falling back to heuristic.", exc)
            # Build a heuristic agent on the fly for this step
            return _HeuristicAgent().inference_step(obs_tuple)

    # ------------------------------------------------------------------
    # Feedback integration
    # ------------------------------------------------------------------

    def process_feedback(self, feedback_dict: Dict[str, Any]) -> None:
        """
        Update agent beliefs / parameters from user feedback.

        feedback_dict keys (all optional):
            action           : str ("clicked" | "dismissed" | "ignored")
            capture_id       : str
            duration_ms      : int
            inferred_topic   : int
        """
        if not self._pymdp_available:
            return

        # Map action string to feedback observation index
        action_str = str(feedback_dict.get("action", "")).lower()
        feedback_map = {"clicked": 1, "dismissed": 2, "ignored": 3}
        feedback_obs = feedback_map.get(action_str, 0)
        logger.debug("Feedback processed: %s → obs %d", action_str, feedback_obs)
        # The agent's belief state is already updated via inference_step;
        # here we can optionally trigger a second inference pass with the
        # feedback observation to refine beliefs.
        try:
            # Dummy observations for non-feedback modalities (keep current)
            obs_feedback = [
                0,            # context: unknown
                0,            # capture: none
                0,            # temporal: recent
                feedback_obs, # actual feedback
            ]
            self._agent.infer_states(obs_feedback)
        except Exception as exc:  # noqa: BLE001
            logger.warning("process_feedback inference failed: %s", exc)
