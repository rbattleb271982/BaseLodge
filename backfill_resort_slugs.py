
"""
One-time migration script to backfill missing Resort.slug values.
Safe to run on production data - only updates NULL slugs.
"""
import re
from app import app, db
from models import Resort


def generate_slug(name, resort_id=None):
    """Generate slug from resort name."""
    # Lowercase and strip whitespace
    slug = name.lower().strip()
    # Replace spaces with hyphens
    slug = slug.replace(" ", "-")
    # Remove non-alphanumeric except hyphens
    slug = re.sub(r'[^a-z0-9-]', '', slug)
    # Remove consecutive hyphens
    slug = re.sub(r'-+', '-', slug)
    # Strip leading/trailing hyphens
    slug = slug.strip('-')
    
    # Append ID if provided for uniqueness
    if resort_id is not None:
        slug = f"{slug}-{resort_id}"
    
    return slug


def ensure_unique_slug(base_slug, resort_id):
    """Ensure slug is unique by checking database and appending ID if needed."""
    # First try the base slug
    existing = Resort.query.filter_by(slug=base_slug).first()
    if not existing or existing.id == resort_id:
        return base_slug
    
    # If conflict, append resort ID
    return f"{base_slug}-{resort_id}"


def backfill_resort_slugs():
    """Backfill missing Resort.slug values."""
    with app.app_context():
        # Find all resorts with NULL slug
        resorts_missing_slug = Resort.query.filter(Resort.slug.is_(None)).all()
        
        if not resorts_missing_slug:
            print("✅ No resorts with missing slugs found.")
            return
        
        print(f"📋 Found {len(resorts_missing_slug)} resorts with missing slugs.")
        print("-" * 70)
        
        updated_count = 0
        
        for resort in resorts_missing_slug:
            # Generate base slug from name
            base_slug = generate_slug(resort.name)
            
            # Ensure uniqueness
            final_slug = ensure_unique_slug(base_slug, resort.id)
            
            # Update the resort
            resort.slug = final_slug
            updated_count += 1
            
            print(f"  ✓ Resort ID {resort.id}: '{resort.name}' → slug: '{final_slug}'")
        
        # Commit all changes
        try:
            db.session.commit()
            print("-" * 70)
            print(f"✅ Successfully updated {updated_count} resorts with slugs.")
        except Exception as e:
            db.session.rollback()
            print(f"❌ Error committing changes: {e}")
            raise


if __name__ == "__main__":
    print("=" * 70)
    print("BACKFILL RESORT SLUGS")
    print("=" * 70)
    backfill_resort_slugs()
    print()
