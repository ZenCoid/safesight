"""Initial tables and hypertable

Revision ID: 001
Revises: None
Create Date: <auto‑generated>
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

# revision identifiers
revision = '001'
down_revision = None
branch_labels = None
depends_on = None

def upgrade():
    # Cameras
    op.create_table(
        'cameras',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('rtsp_url', sa.String(), nullable=False),
        sa.Column('enabled', sa.Boolean(), default=True),
        sa.Column('health_status', sa.String(), default='unknown'),
        sa.Column('current_fps', sa.Float(), default=0.0),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    # Rules
    op.create_table(
        'rules',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('version', sa.String(), default='1.0'),
        sa.Column('enabled', sa.Boolean(), default=True),
        sa.Column('definition', JSONB(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    # Rule‑Camera association
    op.create_table(
        'rule_camera',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column('rule_id', UUID(as_uuid=True), sa.ForeignKey('rules.id', ondelete='CASCADE'), nullable=False),
        sa.Column('camera_id', UUID(as_uuid=True), sa.ForeignKey('cameras.id', ondelete='CASCADE'), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint('rule_id', 'camera_id', name='uq_rule_camera'),
    )
    # ViolationEvents (hypertable)
    op.create_table(
        'violation_events',
        sa.Column('time', sa.DateTime(timezone=True), primary_key=True, server_default=sa.func.now()),
        sa.Column('event_id', UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()")),
        sa.Column('rule_id', UUID(as_uuid=True), nullable=False),
        sa.Column('camera_id', UUID(as_uuid=True), nullable=False),
        sa.Column('detection_snapshot', JSONB()),
        sa.Column('severity', sa.String(), default='warning'),
        sa.Column('acknowledged', sa.Boolean(), default=False),
        sa.Column('clip_path', sa.String()),
    )
    # Indexes for forensic search
    op.create_index('ix_violation_camera_id', 'violation_events', ['camera_id'])
    op.create_index('ix_violation_time_camera', 'violation_events', ['time', 'camera_id'])
    op.create_index('ix_violation_event_id', 'violation_events', ['event_id'])
    # Alerts
    op.create_table(
        'alerts',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column('violation_event_id', UUID(as_uuid=True), nullable=False),
        sa.Column('camera_id', UUID(as_uuid=True), nullable=False),
        sa.Column('escalation_level', sa.Integer(), default=1),
        sa.Column('channel', sa.String()),
        sa.Column('sent', sa.Boolean(), default=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index('ix_alert_violation', 'alerts', ['violation_event_id'])
    op.create_index('ix_alert_camera_time', 'alerts', ['camera_id', 'created_at'])

    # Convert violation_events to TimescaleDB hypertable
    op.execute("SELECT create_hypertable('violation_events', 'time', if_not_exists => TRUE);")

def downgrade():
    op.execute("SELECT drop_hypertable('violation_events');")
    op.drop_table('alerts')
    op.drop_table('violation_events')
    op.drop_table('rule_camera')
    op.drop_table('rules')
    op.drop_table('cameras')