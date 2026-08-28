import pandas as pd

from ui import player_card as PC


def test_set_piece_glyphs_and_line_survive_extraction():
    row = pd.Series({"pens_order": 1, "corners_order": 2, "fk_order": None})
    line = PC.set_piece_line(row)
    glyphs = PC.setpiece_glyphs(row)
    # pens_order == 1 -> the official-order badge, both as a line and a glyph.
    assert "ON PENALTIES" in line
    assert "First-choice penalties" in glyphs


def test_card_ctx_is_plain_data():
    ctx = PC.CardCtx(board=pd.DataFrame(), proj=None, pts_col="consensus_points", fix={},
                     defcon=pd.DataFrame(), scout=None, board_stamp="s")
    assert ctx.on_replace is None and ctx.captain_gw is None
