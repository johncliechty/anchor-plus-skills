// engine/panel/index.mjs — Wave 6: the Triage Panel's library API.
//
// The panel is deliberately split into PURE MODEL and DUMB VIEW, with the
// server owning only transport and authority:
//
//   banners.mjs     what the run must confess, derived from the envelope alone
//   tiles.mjs       findings → tiles, verbatim, with the approval controls that
//                   each class is allowed to have (and, for secrets, none)
//   model.mjs       the whole view as one token-free object
//   render.mjs      that object → HTML, adding no claims of its own
//   apply-state.mjs the persisted pending→applying→done machine (state persists;
//                   the token never does)
//
// Nothing in this directory imports the launch surface, so the panel can be
// modelled and asserted on without binding a socket.

export {
  deriveBanners, canCelebrate, runAgeMs, formatAge, stageNoun,
  BANNER_LEVEL, STAGE_NOUN, AGE_AMBER_MS,
} from './banners.mjs';

export { buildTiles, buildTile, classifyFinding, quarantineNotices, TILE_CLASS, TILE_ORDER } from './tiles.mjs';

export { buildPanelModel, PANEL_MODEL_VERSION } from './model.mjs';

export {
  renderPanelPage, escapeHtml, embedJson, isTokenLive,
  DEAD_APPLY_BANNER_TITLE, DEAD_APPLY_REOPEN_COPY, LIVE_APPLY_F5_FOOTPRINT, DEAD_APPLY_CHIP_LABEL,
  TOKEN_HEADER,
} from './render.mjs';

export {
  readApplyState, beginApply, settleApply, failApply,
  applyStatePathFor, executorSummaryPathFor,
  APPLY_STATE, APPLY_STATE_REFUSAL, APPLY_STATE_VERSION,
} from './apply-state.mjs';
