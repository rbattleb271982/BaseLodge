"""Add pass_brands_json column for multi-pass support

Revision ID: 2743ba21a257
Revises: 9d75b4184d5f
Create Date: 2025-12-31 09:04:40.155190

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.sql import text
import json


# revision identifiers, used by Alembic.
revision = '2743ba21a257'
down_revision = '9d75b4184d5f'
branch_labels = None
depends_on = None


def upgrade():
    # Add the new JSON column
    with op.batch_alter_table('resort', schema=None) as batch_op:
        batch_op.add_column(sa.Column('pass_brands_json', sa.JSON(), nullable=True))

    # Backfill data from legacy pass_brands string column
    connection = op.get_bind()
    
    # Get all resorts with pass_brands data
    result = connection.execute(text("SELECT id, pass_brands, brand FROM resort WHERE pass_brands IS NOT NULL AND pass_brands != ''"))
    
    for row in result:
        resort_id = row[0]
        pass_brands_str = row[1]
        
        if pass_brands_str:
            # Split comma-separated values and clean up
            brands_list = [b.strip() for b in pass_brands_str.split(',') if b.strip()]
            
            # Convert to JSON and update
            if brands_list:
                connection.execute(
                    text("UPDATE resort SET pass_brands_json = :json_val WHERE id = :id"),
                    {"json_val": json.dumps(brands_list), "id": resort_id}
                )


def downgrade():
    with op.batch_alter_table('resort', schema=None) as batch_op:
        batch_op.drop_column('pass_brands_json')
