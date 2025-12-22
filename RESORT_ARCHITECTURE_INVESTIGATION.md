# Resort Architecture Investigation Report
**Date:** December 22, 2025  
**Scope:** Comprehensive audit of resort data storage, querying, and rendering across BaseLodge

---

## Executive Summary

BaseLodge currently uses a **fragmented resort storage architecture** with critical inconsistencies. The canonical `Resort` table exists but is used inconsistently across different features. **Visited Mountains and Wishlist Mountains use fundamentally different storage approaches**, creating a source of truth problem.

### Key Finding
- **Trip resorts:** Use Resort table IDs (correct, normalized)
- **Wishlist resorts:** Use Resort table IDs (correct, normalized)
- **Visited mountains:** Use hardcoded string values from MOUNTAINS_BY_STATE constant (legacy, denormalized)
- **Home mountain:** Uses string values (legacy, denormalized)

This inconsistency is both **intentional drift** (legacy codebase) and **unintentional separation** (different features built at different times).

---

## 1. Resort Source of Truth

### The Canonical Resort Model (✓ Well-Defined)

**Table:** `resort` (SQLAlchemy model: `Resort` in `models.py` line 221)

**Schema:**
```python
class Resort(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    state = db.Column(db.String(50), nullable=False)  # Region code: CO, CA, Hokkaido, etc.
    state_full = db.Column(db.String(50), nullable=True)  # Full name: Colorado, California, etc.
    country = db.Column(db.String(2), nullable=True)  # ISO-2 code: US, CA, FR, etc.
    brand = db.Column(db.String(20), nullable=True)  # 'Epic', 'Ikon', 'Indy', 'Other'
    pass_brands = db.Column(db.String(150), nullable=True)  # Comma-separated: 'Epic', 'Ikon,MountainCollective', etc.
    slug = db.Column(db.String(120), unique=True, nullable=False)
    is_active = db.Column(db.Boolean, default=True)
    
    # Relationships
    trips = db.relationship('SkiTrip', backref='resort', lazy=True)
```

**Current Coverage:**
- ✅ Populated via admin seeding endpoints (Colorado, Utah, Washington, California, Eastern, Western, Canadian resorts)
- ✅ Supports multi-country resorts (US, Canada, Japan, France, etc.)
- ✅ Tracks pass brand affiliation and multiple pass compatibility

**Access Pattern:**
```
Resort.query.get(resort_id)  # By ID
Resort.query.filter_by(is_active=True).order_by(Resort.state, Resort.name)  # All active
Resort.query.filter(Resort.id.in_(id_list))  # By ID list
```

---

## 2. Visited vs. Wishlist Storage: Critical Difference

### Visited Mountains (❌ Inconsistent - String-Based)

**Storage Location:** `User.mountains_visited` (JSON array in `models.py` line 77)

```python
mountains_visited = db.Column(db.JSON, default=list)
```

**Data Type:** **Array of mountain name STRINGS** (not Resort IDs)

**Source Data:** Hardcoded from `MOUNTAINS_BY_STATE` constant (`app.py` line 510)
```python
MOUNTAINS_BY_STATE = {
    "CO": ["Vail", "Breckenridge", "Keystone", ...],
    "UT": ["Park City", "Deer Valley", "Snowbird", ...],
    "CA": ["Mammoth Mountain", "Palisades Tahoe", ...],
    # ... 16 US states + territories
}
```

**What This Means:**
- Visited mountains are **entirely disconnected from the Resort table**
- No way to look up resort metadata (pass brands, country, etc.) without string matching
- If a resort name exists in both MOUNTAINS_BY_STATE and Resort table, they are **separate records**
- Cannot easily filter visited mountains by pass brand or country

**Example Stored Value:**
```json
{"mountains_visited": ["Vail", "Park City", "Breckenridge"]}
```

---

### Wishlist Resorts (✓ Consistent - ID-Based)

**Storage Location:** `User.wish_list_resorts` (JSON array in `models.py` line 79)

```python
wish_list_resorts = db.Column(db.JSON, default=list)  # List of resort IDs (max 3)
```

**Data Type:** **Array of Resort.id (integers)**

**Constraint:** Maximum 3 resorts per user

**What This Means:**
- Wishlist resorts are **fully normalized**, directly referencing the Resort table
- Can access all resort metadata with a single relationship lookup
- Can filter by pass brand, country, etc.
- Enforced via validation (`app.py` line 2260-2268)

**Example Stored Value:**
```json
{"wish_list_resorts": [14, 28, 42]}
```

**Query Pattern (Example from `app.py` line 2245):**
```python
wish_list_resorts = Resort.query.filter(Resort.id.in_(wish_list_ids)).all() if wish_list_ids else []
```

---

### Home Mountain (❌ Inconsistent - String-Based)

**Storage Location:** `User.home_mountain` (string in `models.py` line 76)

```python
home_mountain = db.Column(db.String(100), nullable=True)
```

**Data Type:** Mountain name STRING (from MOUNTAINS_BY_STATE)

**Validation:** Only allows mountains from the user's selected `home_state`

**What This Means:**
- Same issue as `mountains_visited`—denormalized, string-based
- Cannot lookup pass brands or other metadata
- Duplication possible if a mountain exists in both systems

---

## 3. All Resort Selection Surfaces

### A. Trip Creation & Editing

**Endpoints:**
- `GET /add_trip` (line 2307)
- `POST /add_trip` (line 2307)
- `GET /trips/<trip_id>/edit` (line 2455)
- `POST /trips/<trip_id>/edit` (line 2455)

**Data Flow:**
1. **Query:** `Resort.query.filter_by(is_active=True).order_by(Resort.state, Resort.name).all()`
2. **Write:** `SkiTrip.resort_id = resort.id` (FK to Resort)
3. **Source of Truth:** ✅ Resort table (normalized)

**Template:** `templates/add_trip.html`
- Displays all resorts in state-grouped dropdowns
- Smart sorting by user's pass type and home state

**Associated Feature:** Set home mountain checkbox (line 2319)
```python
set_home_mountain = request.form.get("set_home_mountain") == "on"
# Updates User.home_mountain = resort.name (string, not ID)
```

---

### B. Visited Mountains (Mark as Visited)

**Endpoint:**
- `GET /mountains-visited` (line 2619)
- `POST /mountains-visited` (line 2619)
- Alias: `GET /settings/mountains-visited` → redirect to above (line 2223)

**Data Flow:**
1. **Query:** Hardcoded `MOUNTAINS_BY_STATE` constant (no database lookup)
2. **Write:** `User.mountains_visited = selected_mountains` (array of strings)
3. **Source of Truth:** ❌ MOUNTAINS_BY_STATE constant (denormalized)

**Template:** `templates/mountains_visited.html`
- State-grouped checkboxes from MOUNTAINS_BY_STATE
- Displays count of selected mountains
- No link to Resort table

**Key Code (app.py line 2624-2630):**
```python
for state, state_mountains in MOUNTAINS_BY_STATE.items():
    for mtn in state_mountains:
        all_mountains.append(mtn)
        mountains_with_state[mtn] = state
```

---

### C. Wishlist / Bucket List Resorts

**Endpoint:**
- `GET /settings/wish-list` (line 2235)
- `POST /settings/wish-list/save` (line 2253)

**Data Flow:**
1. **Query:** `Resort.query.filter_by(is_active=True).order_by(Resort.state, Resort.name).all()`
2. **Write:** `User.wish_list_resorts = valid_ids` (array of Resort IDs)
3. **Source of Truth:** ✅ Resort table (normalized)

**Template:** `templates/settings_wish_list.html`
- State-grouped checkboxes from Resort table
- Enforces max 3 selection limit (line 2260)
- Live JavaScript counter

**Validation (app.py line 2265-2268):**
```python
for rid in resort_ids:
    resort = Resort.query.get(rid)
    if resort:
        valid_ids.append(rid)
```

---

### D. API Endpoints

#### `/api/mountains/<state>` (line 860)
**Purpose:** Fetch mountain list for a state (mobile/dynamic UI)

**Data Source:** `MOUNTAINS_BY_STATE` constant
```python
mountains = MOUNTAINS_BY_STATE.get(state_code, [])
```

**Returns:** Array of mountain name strings

**Usage Context:** Used during trip creation for dynamic dropdown filtering

---

#### `/api/trip/create` (line 866)
**Purpose:** Create trip via AJAX (mobile-first)

**Data Source:** Resort ID from form
```python
resort_id = request.json.get("resort_id")
resort = Resort.query.get(resort_id)
```

**Storage:** `SkiTrip.resort_id` (FK to Resort table)

---

#### `/api/trip/<trip_id>/edit` (line 941)
**Purpose:** Edit trip via AJAX

**Data Source:** Resort ID
**Storage:** Updates `SkiTrip.resort_id`

---

### E. Friend Profiles (Wishlist Display)

**Endpoint:**
- `GET /friend/<friend_id>` (line 1290)

**Data Flow:**
1. **Query:** `Resort.query.filter(Resort.id.in_(friend_wish_list_ids)).all()`
2. **Display:** Friend's wishlist with overlap highlighting
3. **Source of Truth:** ✅ Resort table

**Template Logic (app.py line 1329-1335):**
```python
friend_wish_list_ids = friend.wish_list_resorts or []
friend_wish_list = Resort.query.filter(Resort.id.in_(friend_wish_list_ids)).all() if friend_wish_list_ids else []

user_wish_list_ids = set(user.wish_list_resorts or [])
wish_list_overlap_ids = [rid for rid in friend_wish_list_ids if rid in user_wish_list_ids]
wish_list_overlap = Resort.query.filter(Resort.id.in_(wish_list_overlap_ids)).all() if wish_list_overlap_ids else []
```

---

### F. Home Page / Dashboard (Statistics & Overlaps)

**Endpoint:** `GET /home` (line 1395)

**Data Flows:**

**1. User's Wishlist Display:**
```python
wish_list_ids = current_user.wish_list_resorts or []
wish_list_resorts = Resort.query.filter(Resort.id.in_(wish_list_ids)).all()
```

**2. Visited Mountains Display:**
```python
mountains_visited_count = len(current_user.mountains_visited or [])
# Only count is displayed, no Resort lookup
```

**3. Wishlist Overlap with Friends:**
```python
for resort_id in user_wish_list:
    for other_user in friends:
        other_wish_list = other_user.wish_list_resorts or []
        if resort_id in other_wish_list:
            # Mark as overlap
```

**4. Shared Wishlist Discovery:**
```python
# Find friends with matching wishlist items
resort_counts[resort_id] = count_of_friends_with_same_resort
resort = Resort.query.get(resort_id)  # Lookup for display
```

**Templates Involved:**
- `templates/home.html` (lines 406-424 for wishlist display)
- Stats show count of wishlist resorts with accordion expansion
- No visited mountains display on home (only on profile cards and settings)

---

### G. Admin/Seeding Endpoints

**Endpoints (Resort Database Population):**
- `/admin/seed-colorado-resorts` (line 3698)
- `/admin/seed-utah-resorts` (line 3761)
- `/admin/seed-wa-ca-resorts` (line 3828)
- `/admin/seed-western-resorts` (line 3924)
- `/admin/seed-eastern-resorts` (line 4053)
- `/admin/seed-canadian-resorts` (line 4271)

**Data Flow:**
1. Create/insert Resort records with full metadata
2. Resorts immediately available in trip creation, wishlist selection
3. Does NOT update MOUNTAINS_BY_STATE constant (hardcoded)

**Key Observation:** Resort table is populated from admin endpoints, but MOUNTAINS_BY_STATE is a separate, hardcoded constant. They can diverge.

---

### H. Group Trips (Social Feature)

**Endpoint:** `/api/group-trip/create` (line 4430)

**Data Flow:**
1. **Query:** `Resort.query.get(resort_id)` (from request)
2. **Store:** `GroupTrip.resort_id` (FK to Resort table)
3. **Source of Truth:** ✅ Resort table

**Note:** GroupTrip model (line 344 in models.py) uses the same pattern as SkiTrip—resort_id as FK.

---

## 4. Consistency and Drift Analysis

### Inconsistencies Found

| **Feature** | **Storage** | **Data Type** | **Source** | **Query Cost** | **Status** |
|---|---|---|---|---|---|
| **Trip Resorts** | `SkiTrip.resort_id` | Integer FK | Resort table | O(1) lookup | ✅ Normalized |
| **Wishlist Resorts** | `User.wish_list_resorts` | JSON array of IDs | Resort table | O(n) filter | ✅ Normalized |
| **Visited Mountains** | `User.mountains_visited` | JSON array of strings | MOUNTAINS_BY_STATE | O(n) linear search | ❌ Denormalized |
| **Home Mountain** | `User.home_mountain` | String | MOUNTAINS_BY_STATE | O(n) linear search | ❌ Denormalized |
| **GroupTrip Resorts** | `GroupTrip.resort_id` | Integer FK | Resort table | O(1) lookup | ✅ Normalized |

### Root Cause Analysis

**Why the Inconsistency?**

1. **Visited Mountains** is legacy (likely early feature)
   - Built around MOUNTAINS_BY_STATE before Resort table was comprehensive
   - No FK constraint enforced
   - Still widely used (profile stats, onboarding hints)

2. **Wishlist Resorts** is newer/refactored
   - Uses Resort table IDs consistently
   - Enforces constraints (max 3)
   - Takes advantage of full resort metadata

3. **Intentional Separation** (evidence)
   - Comments in code: `# List of resort IDs (max 3)` vs `# [implicit: mountain names]`
   - Different validation logic for each
   - Different query patterns

4. **Not Yet Unified** (evidence)
   - MOUNTAINS_BY_STATE constant still hardcoded (510-526 in app.py)
   - No migration code to convert mountains_visited to resort IDs
   - Two parallel systems coexist

---

## 5. Risk Assessment

### High Risk: Data Sync Issues

**Scenario:** A mountain exists in both systems with slightly different names
```
MOUNTAINS_BY_STATE: "Mt. Hood Meadows"
Resort table: "Mt. Hood Meadows" (id=47)
Resort table: "Mt Hood Meadows" (id=112) ← spelling variant
```

**Impact:**
- User marks "Mt. Hood Meadows" as visited → stored as string
- User adds "Mt Hood Meadows" to wishlist → stored as resort ID
- No clear way to reconcile these as the same place

---

### Medium Risk: Feature Gaps

**Visited Mountains Cannot:**
- ❌ Filter by pass brand (no Resort data)
- ❌ Show country/region metadata
- ❌ Link to trip details (no FK to SkiTrip)
- ❌ Sort by geography beyond state
- ❌ Calculate analytics across systems

**Wishlist Can Do These, Visited Cannot**

---

### Low Risk: Performance

- **Visited Mountains:** O(n) string matching, but dataset is small (~200 mountains)
- **Wishlist:** O(n) filter by IDs, max 3 items per user, negligible impact
- **No scaling concerns** at current dataset size

---

## 6. Display Consistency

### How They're Shown to Users

**Profile Cards (Friend Profiles):**
```
Visited Mountains: Count displayed
↓ Example: "6 mountains visited"
[Read-only display of count, no expansion]

Wishlist Mountains: Count with accordion expansion
↓ Example: "3 resorts" → [Vail, Park City, Snowbird]
[Interactive, expandable list]
```

**Templates:**
- `templates/friend_profile.html` (line 247 for visited, line 290 for wishlist overlap)
- `templates/home.html` (line 406-424 for wishlist, line 80-90 for visited)
- `templates/components/profile_summary.html` (if used)

**Settings Page:**
- `/settings/mountains-visited` → links to `mountains_visited.html`
- `/settings/wish-list` → links to `settings_wish_list.html`

Both are accessible, editable, but use completely different backends.

---

## 7. Recommendations for Unification

### Option A: Migrate Visited Mountains → Resort Table IDs (Recommended)

**Approach:**
1. Create migration script to convert `User.mountains_visited` strings → Resort IDs
   - For each mountain name in MOUNTAINS_BY_STATE, find matching Resort record
   - Fall back to creating Resort records for unmatched mountains
   
2. Store as: `User.visited_resort_ids` (JSON array of IDs, similar to wishlist)

3. Keep `mountains_visited` field for backward compatibility (marked deprecated)

4. Update queries to use Resort table

**Pros:**
- Single source of truth (Resort table)
- Enables filtering by pass brand, country
- Consistent with wishlist and trip patterns
- Reduces code duplication
- Opens door to advanced features (analytics, recommendations)

**Cons:**
- Requires data migration
- Some mountains may not exist in Resort table (Hokkaido, France, etc.)

**Implementation Cost:** Medium (3-5 endpoints to update, 1 migration)

---

### Option B: Keep Two Systems, Improve Documentation

**Approach:**
1. Explicitly document the split in code comments
2. Add validation to prevent name collisions
3. Create helper functions for each system
4. No schema changes

**Pros:**
- Zero migration risk
- Maintains MOUNTAINS_BY_STATE as reference data
- Works immediately

**Cons:**
- Perpetuates technical debt
- Harder to maintain long-term
- Feature parity issues between systems

---

### Option C: Consolidate to MOUNTAINS_BY_STATE Only

**Approach:**
1. Remove Resort table references from visited/wishlist
2. Regenerate MOUNTAINS_BY_STATE from comprehensive mountain database
3. Use strings everywhere (visited, wishlist, trips)

**Pros:**
- Simplest code path
- No FK constraints needed

**Cons:**
- Loss of metadata (pass brands, country codes)
- Regression for wishlist functionality
- Harder to scale internationally

---

## 8. Current Data Integrity

**No Foreign Key Constraints:**
- `User.wish_list_resorts` stores IDs but no FK constraint
- Validation happens in application code only
- Orphaned resort IDs possible if resort is deleted

**No Cascading Delete Protection:**
- Deleting a Resort doesn't clean up wish_list_resorts arrays
- No triggers or application-level cleanup

**Recommendation:** Add application-level validation and consider FK constraints for future schema updates.

---

## Summary Table

| Aspect | Status | Recommendation |
|--------|--------|-----------------|
| **Canonical Resort Table** | ✅ Exists and well-defined | Keep and expand |
| **Trip Resorts** | ✅ Uses Resort table (normalized) | No change needed |
| **Wishlist Resorts** | ✅ Uses Resort table (normalized) | No change needed |
| **Visited Mountains** | ❌ Uses hardcoded strings (denormalized) | Migrate to Resort IDs |
| **Home Mountain** | ❌ Uses hardcoded strings (denormalized) | Consider migration |
| **Source of Truth** | ⚠️ Split between Resort table and MOUNTAINS_BY_STATE | Consolidate on Resort table |
| **Consistency Across Surfaces** | ❌ Inconsistent storage patterns | Unify via Option A |

---

## Conclusion

The Resort architecture is **partially unified** with critical gaps. Trips and Wishlist use the canonical Resort table correctly, but Visited Mountains and Home Mountain remain denormalized string-based storage. This creates:

1. **No single source of truth** for what mountains/resorts exist
2. **Feature gaps** in visited mountains (no metadata access)
3. **Data integrity risks** (duplication, orphaning)
4. **Technical debt** (two parallel systems)

**Recommended Next Step:** Implement Option A (migrate visited mountains to Resort table IDs) to achieve complete unification while maintaining backward compatibility.
