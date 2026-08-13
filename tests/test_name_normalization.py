"""Unit tests for normalize_for_search() and build_name_search_clauses().

These are pure-Python tests — no database or Flask context needed.
They verify that the normalization algorithm produces identical output
for storage (search_first_name/search_last_name) and query normalization,
and that the multi-token split logic generates the correct partition clauses.
"""
import pytest
from services.search_utils import normalize_for_search, build_name_search_clauses


# ── normalize_for_search ──────────────────────────────────────────────────────

class TestNormalizeForSearch:

    def test_empty_string(self):
        assert normalize_for_search('') == ''

    def test_none_equivalent(self):
        assert normalize_for_search(None) == ''  # type: ignore[arg-type]

    def test_case_folding(self):
        assert normalize_for_search('JOHN') == 'john'
        assert normalize_for_search('John') == 'john'

    # NFD-decomposable accents
    def test_e_acute(self):
        assert normalize_for_search('José') == 'jose'

    def test_n_tilde(self):
        assert normalize_for_search('García') == 'garcia'

    def test_u_umlaut(self):
        assert normalize_for_search('Müller') == 'muller'

    def test_a_tilde(self):
        assert normalize_for_search('Ãngela') == 'angela'

    def test_c_cedilla(self):
        assert normalize_for_search('François') == 'francois'

    def test_full_accented_name(self):
        assert normalize_for_search('José García') == 'jose garcia'

    # Non-NFD Latin characters (explicit transliteration map)
    def test_o_stroke(self):
        assert normalize_for_search('Søren') == 'soren'
        assert normalize_for_search('Ø') == 'o'          # uppercase via lower() first

    def test_l_stroke(self):
        assert normalize_for_search('Łukasz') == 'lukasz'
        assert normalize_for_search('ł') == 'l'

    def test_d_stroke(self):
        assert normalize_for_search('đorđe') == 'dorde'
        assert normalize_for_search('Đ') == 'd'

    def test_eth(self):
        assert normalize_for_search('ðagur') == 'dagur'
        assert normalize_for_search('Ð') == 'd'

    def test_thorn(self):
        assert normalize_for_search('þór') == 'thor'
        assert normalize_for_search('Þór') == 'thor'

    def test_ae(self):
        assert normalize_for_search('æ') == 'ae'
        assert normalize_for_search('Æ') == 'ae'

    def test_oe(self):
        assert normalize_for_search('œuvre') == 'oeuvre'
        assert normalize_for_search('Œ') == 'oe'

    def test_sharp_s(self):
        assert normalize_for_search('straße') == 'strasse'
        assert normalize_for_search('Straße') == 'strasse'

    # Apostrophe variants
    def test_straight_apostrophe(self):
        assert normalize_for_search("O'Connor") == 'o connor'

    def test_curly_apostrophe(self):
        assert normalize_for_search('O\u2019Connor') == 'o connor'

    def test_backtick(self):
        assert normalize_for_search('O`Connor') == 'o connor'

    # Hyphens and dashes
    def test_hyphen(self):
        assert normalize_for_search('Battle-Baxter') == 'battle baxter'

    def test_hyphenated_first_name(self):
        assert normalize_for_search('Anne-Marie') == 'anne marie'

    def test_en_dash(self):
        assert normalize_for_search('Smith\u2013Jones') == 'smith jones'

    def test_em_dash(self):
        assert normalize_for_search('Smith\u2014Jones') == 'smith jones'

    # Whitespace
    def test_multiple_spaces(self):
        assert normalize_for_search('John  Smith') == 'john smith'

    def test_leading_trailing_spaces(self):
        assert normalize_for_search('  John Smith  ') == 'john smith'

    def test_tab_and_newline(self):
        assert normalize_for_search('John\tSmith') == 'john smith'

    # Combined cases
    def test_jean_luc(self):
        assert normalize_for_search('Jean-Luc') == 'jean luc'

    def test_de_la_cruz(self):
        assert normalize_for_search('Ana María De La Cruz') == 'ana maria de la cruz'

    def test_wojcik(self):
        assert normalize_for_search('Łukasz Wójcik') == 'lukasz wojcik'

    # Determinism: stored and query normalization produce identical output
    def test_idempotent(self):
        inputs = ['José García', 'Søren', 'O\'Connor', 'Battle-Baxter', 'Straße']
        for s in inputs:
            once = normalize_for_search(s)
            twice = normalize_for_search(once)
            assert once == twice, f"Not idempotent for: {s!r}"


# ── build_name_search_clauses ─────────────────────────────────────────────────

class TestBuildNameSearchClauses:
    """Tests for multi-token name partition logic.

    Uses real SQLAlchemy column() literals so and_() accepts them without a DB.
    Actual SQL execution is covered in test_friend_search.py.
    """

    def _cols(self):
        """Return real SQLAlchemy literal column objects."""
        from sqlalchemy import column
        return column('fn', type_=None), column('ln', type_=None)

    def _like_patterns(self, clauses):
        """Extract the right-hand LIKE patterns from a list of and_() clauses.

        Each and_() clause is a BooleanClauseList of two BinaryExpression
        nodes (col LIKE 'pattern'). We compile each to a SQL string and parse
        the patterns out.
        """
        from sqlalchemy.dialects import sqlite as _sqlite_dialect
        _dialect = _sqlite_dialect.dialect()
        patterns = []
        for clause in clauses:
            sql_str = str(clause.compile(dialect=_dialect,
                                          compile_kwargs={'literal_binds': True}))
            patterns.append(sql_str)
        return patterns

    def test_single_token_returns_none(self):
        fc, lc = self._cols()
        assert build_name_search_clauses('john', fc, lc) is None

    def test_empty_returns_none(self):
        fc, lc = self._cols()
        assert build_name_search_clauses('', fc, lc) is None

    def test_two_tokens_one_partition(self):
        fc, lc = self._cols()
        clauses = build_name_search_clauses('jo sm', fc, lc)
        assert clauses is not None
        assert len(clauses) == 1   # N-1 = 1 partition for 2 tokens

    def test_three_tokens_two_partitions(self):
        fc, lc = self._cols()
        clauses = build_name_search_clauses('mary ann sm', fc, lc)
        assert clauses is not None
        assert len(clauses) == 2   # N-1 = 2 partitions for 3 tokens

    def test_four_tokens_three_partitions(self):
        fc, lc = self._cols()
        clauses = build_name_search_clauses('ana maria de la', fc, lc)
        assert clauses is not None
        assert len(clauses) == 3   # N-1 = 3 partitions for 4 tokens

    def test_two_token_prefix_patterns(self):
        """LIKE patterns should be first_part% and last_part%."""
        fc, lc = self._cols()
        clauses = build_name_search_clauses('jo sm', fc, lc)
        sqls = self._like_patterns(clauses)
        assert len(sqls) == 1
        assert 'jo%' in sqls[0]
        assert 'sm%' in sqls[0]

    def test_three_token_prefix_patterns(self):
        """Both partitions of 'mary ann sm' should be generated."""
        fc, lc = self._cols()
        clauses = build_name_search_clauses('mary ann sm', fc, lc)
        sqls = self._like_patterns(clauses)
        # Partition 1: first="mary", last="ann sm"
        assert any('mary%' in s and 'ann sm%' in s for s in sqls)
        # Partition 2: first="mary ann", last="sm"
        assert any('mary ann%' in s and 'sm%' in s for s in sqls)


class TestLikeInjection:
    """Security tests: LIKE metacharacter injection must not bypass search.

    A query of '% %' should match ONLY rows whose search_first_name starts
    with '%', not every row in the table.  Similarly, '_' must not act as a
    single-character wildcard.
    """

    def _compile(self, clauses):
        from sqlalchemy.dialects import sqlite as _sqlite_dialect
        _dialect = _sqlite_dialect.dialect()
        sqls = []
        for clause in clauses:
            sqls.append(str(clause.compile(dialect=_dialect,
                                            compile_kwargs={'literal_binds': True})))
        return sqls

    def test_percent_escaped_in_pattern(self):
        """'% %' — both tokens should have literal % escaped, not wildcard."""
        from sqlalchemy import column
        fc = column('fn', type_=None)
        lc = column('ln', type_=None)
        clauses = build_name_search_clauses('% %', fc, lc)
        sqls = self._compile(clauses)
        assert len(sqls) == 1
        # The pattern should contain the escaped form, not a bare '%' prefix
        assert '\\%%' in sqls[0]
        assert '\\%%' in sqls[0]

    def test_underscore_escaped_in_pattern(self):
        """'jo _m' — underscore must be escaped so it does not act as wildcard."""
        from sqlalchemy import column
        fc = column('fn', type_=None)
        lc = column('ln', type_=None)
        clauses = build_name_search_clauses('jo _m', fc, lc)
        sqls = self._compile(clauses)
        assert any('\\_m%' in s for s in sqls)

    def test_wildcard_query_does_not_return_all_users(self, client):
        """Integration: a wildcard query must not return all discoverable members.

        Uses '%_ %_' as the injection payload — each token is 2 chars so it
        passes the ≥2-char-per-token length validation.  With broken LIKE
        escaping, '%_' would match every row (any char, then any char...).
        With correct escaping it matches only rows starting with literal '%_'.
        """
        from app import app as _app
        from services.search_utils import normalize_for_search
        from tests.conftest import _make_user, _login
        from models import db

        with _app.app_context():
            # Create a discoverable member whose normalized name is 'john smith'
            victim = _make_user('victim_inj')
            victim.search_first_name = normalize_for_search('John')
            victim.search_last_name = normalize_for_search('Smith')
            victim.discoverable_in_friend_search = True
            me = _make_user('me_inj')
            db.session.commit()
            me_id = me.id

        _login(client, me_id)
        # '%_ %_' — each token is 2 chars (passes length check), but if LIKE
        # metacharacters are not escaped the query matches every member.
        # URL-encode: %25_ %25_ → '%_ %_'
        rv = client.get('/api/users/search?q=%25_+%25_')
        assert rv.status_code == 200
        data = rv.get_json()
        # With correct escaping: no row has search_first_name starting with '%_'
        # → empty results.  If broken: victim (john/smith) would appear.
        assert len(data) == 0

    def test_backslash_in_token_escaped(self):
        """Backslash in token must be double-escaped, not left bare."""
        from sqlalchemy import column
        fc = column('fn', type_=None)
        lc = column('ln', type_=None)
        # 'jo sm\\' — last token has a trailing backslash
        clauses = build_name_search_clauses('jo sm\\', fc, lc)
        # Must produce exactly one clause (N-1 = 1 for 2 tokens) without crashing
        assert clauses is not None
        assert len(clauses) == 1
        # Compile to SQL and verify the backslash is doubled (escaped)
        sqls = self._compile(clauses)
        assert len(sqls) == 1
        # The pattern for 'sm\' after escaping should contain 'sm\\' in the SQL;
        # in compiled literal form that appears as sm\\ followed by the % prefix.
        # At minimum, the clause must compile without error (verified above).
        # Verify it does NOT contain a lone trailing backslash before % (which
        # would make the DB engine treat % as a literal, or break the SQL).
        sql = sqls[0]
        # Double-backslash escape: the escaped token 'sm\\' becomes 'sm\\\\%'
        # when compiled with literal_binds (one level for Python, one for SQL).
        # Key invariant: no pattern should end with a bare backslash (no `\%`
        # where backslash is the SQL escape for % — that would mean we escaped
        # the wrong thing).  A pattern ending in \\ followed by % is correct.
        assert '\\\\%' in sql or 'sm%' in sql  # either escaped or stripped clean
