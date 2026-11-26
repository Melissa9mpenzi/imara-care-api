"""Initial clinical schema

Revision ID: 44591a43fda8
Revises: None
Create Date: 2026-11-26 10:57:38.173376

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '44591a43fda8'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names()) - {"alembic_version"}
    expected_tables = set(['appointments', 'audit_events', 'billing_invoice_details', 'billing_invoice_lines', 'billing_invoices', 'billing_payment_receipts', 'billing_payments', 'departments', 'facilities', 'insurance_claims', 'job_runs', 'laboratory_orders', 'laboratory_result_reviews', 'laboratory_samples', 'medication_orders', 'medication_stock_batches', 'medication_stock_items', 'medication_stock_movements', 'notifications', 'patients', 'queue_entries', 'reminder_occurrences', 'reminders', 'support_requests', 'theatre_procedures', 'triage_records', 'visit_handoffs', 'visits'])
    if not existing_tables.issubset(expected_tables):
        unexpected = sorted(existing_tables - expected_tables)
        raise RuntimeError(f"Refusing baseline migration with unexpected tables: {unexpected}")
    required_columns = {'appointments': ['appointment_type',
                      'cancellation_reason',
                      'clinician',
                      'created_at',
                      'department_id',
                      'ends_at',
                      'facility_id',
                      'id',
                      'notes',
                      'patient_id',
                      'reason',
                      'starts_at',
                      'status'],
     'audit_events': ['action',
                      'actor',
                      'created_at',
                      'details',
                      'entity_id',
                      'entity_type',
                      'facility_id',
                      'id'],
     'billing_invoice_details': ['bill_to_name',
                                 'bill_to_phone',
                                 'created_at',
                                 'due_date',
                                 'insurer_name',
                                 'invoice_id',
                                 'notes',
                                 'payer_reference',
                                 'payer_type',
                                 'service_date'],
     'billing_invoice_lines': ['amount',
                               'description',
                               'id',
                               'invoice_id',
                               'position',
                               'quantity',
                               'unit',
                               'unit_price'],
     'billing_invoices': ['created_at',
                          'created_by',
                          'description',
                          'facility_id',
                          'id',
                          'invoice_number',
                          'patient_id',
                          'status',
                          'total_amount'],
     'billing_payment_receipts': ['facility_id',
                                  'issued_at',
                                  'issued_by',
                                  'payment_id',
                                  'receipt_number'],
     'billing_payments': ['amount',
                          'facility_id',
                          'id',
                          'invoice_id',
                          'method',
                          'paid_at',
                          'recorded_by',
                          'reference'],
     'departments': ['active', 'code', 'facility_id', 'id', 'name', 'queue_prefix', 'type'],
     'facilities': ['code',
                    'created_at',
                    'currency',
                    'id',
                    'name',
                    'next_patient_number',
                    'timezone'],
     'insurance_claims': ['claim_number',
                          'created_at',
                          'created_by',
                          'external_claim_reference',
                          'facility_id',
                          'id',
                          'invoice_id',
                          'notes',
                          'resolved_at',
                          'status',
                          'submitted_at',
                          'updated_at',
                          'updated_by'],
     'job_runs': ['error',
                  'finished_at',
                  'id',
                  'name',
                  'processed_count',
                  'started_at',
                  'status'],
     'laboratory_orders': ['clinical_notes',
                           'created_at',
                           'facility_id',
                           'id',
                           'ordered_by',
                           'patient_id',
                           'priority',
                           'result',
                           'resulted_at',
                           'resulted_by',
                           'specimen',
                           'status',
                           'test_name'],
     'laboratory_result_reviews': ['facility_id',
                                   'id',
                                   'notes',
                                   'order_id',
                                   'reviewed_at',
                                   'reviewed_by'],
     'laboratory_samples': ['collected_at',
                            'collected_by',
                            'facility_id',
                            'id',
                            'order_id',
                            'status',
                            'updated_at',
                            'updated_by'],
     'medication_orders': ['created_at',
                           'dispensed_at',
                           'dispensed_by',
                           'dosage',
                           'duration',
                           'facility_id',
                           'frequency',
                           'id',
                           'instructions',
                           'patient_id',
                           'prescribed_by',
                           'quantity',
                           'status',
                           'stock_item_id'],
     'medication_stock_batches': ['batch_number',
                                  'expires_on',
                                  'facility_id',
                                  'id',
                                  'quantity_received',
                                  'quantity_remaining',
                                  'received_at',
                                  'received_by',
                                  'stock_item_id'],
     'medication_stock_items': ['active',
                                'created_at',
                                'facility_id',
                                'form',
                                'id',
                                'name',
                                'quantity_on_hand',
                                'reorder_level',
                                'strength',
                                'unit',
                                'unit_price',
                                'updated_at'],
     'medication_stock_movements': ['created_at',
                                    'created_by',
                                    'facility_id',
                                    'id',
                                    'movement_type',
                                    'quantity',
                                    'reference',
                                    'stock_item_id'],
     'notifications': ['body',
                       'created_at',
                       'facility_id',
                       'id',
                       'link_id',
                       'link_type',
                       'priority',
                       'read_at',
                       'recipient_user_id',
                       'reminder_occurrence_id',
                       'snoozed_until',
                       'status',
                       'title',
                       'type'],
     'patients': ['address',
                  'allergies',
                  'alt_phone',
                  'created_at',
                  'date_of_birth',
                  'email',
                  'estimated_age',
                  'facility_id',
                  'first_name',
                  'id',
                  'last_name',
                  'national_id',
                  'next_of_kin_name',
                  'next_of_kin_phone',
                  'next_of_kin_relationship',
                  'other_names',
                  'patient_number',
                  'phone',
                  'sex',
                  'sms_consent',
                  'status',
                  'updated_at',
                  'usual_payment_method'],
     'queue_entries': ['arrived_at',
                       'called_at',
                       'called_by',
                       'department_id',
                       'facility_id',
                       'id',
                       'priority',
                       'queue_date',
                       'queue_number',
                       'status',
                       'visit_id'],
     'reminder_occurrences': ['acknowledged_at',
                              'alert_offset_minutes',
                              'fire_at',
                              'fired_at',
                              'id',
                              'reminder_id',
                              'snoozed_until',
                              'status'],
     'reminders': ['alert_offsets',
                   'created_at',
                   'created_by',
                   'due_at',
                   'facility_id',
                   'id',
                   'link_id',
                   'link_type',
                   'note',
                   'owner_id',
                   'priority',
                   'repeat_frequency',
                   'repeat_interval',
                   'repeat_until',
                   'status',
                   'timezone',
                   'title',
                   'updated_at'],
     'support_requests': ['category',
                          'created_at',
                          'facility_id',
                          'id',
                          'message',
                          'requester_email',
                          'requester_id',
                          'requester_name',
                          'requester_role',
                          'status',
                          'subject',
                          'ticket_number',
                          'updated_at',
                          'updated_by'],
     'theatre_procedures': ['created_at',
                            'created_by',
                            'facility_id',
                            'id',
                            'lead_clinician',
                            'notes',
                            'patient_id',
                            'procedure_name',
                            'scheduled_at',
                            'status'],
     'triage_records': ['blood_sugar',
                        'bmi',
                        'created_at',
                        'diastolic',
                        'facility_id',
                        'height',
                        'id',
                        'notes',
                        'pain_score',
                        'priority',
                        'pulse',
                        'recorded_by',
                        'respiratory_rate',
                        'spo2',
                        'systolic',
                        'temperature',
                        'visit_id',
                        'weight'],
     'visit_handoffs': ['created_at',
                        'created_by',
                        'facility_id',
                        'id',
                        'reason',
                        'source_department_id',
                        'source_visit_id',
                        'target_department_id',
                        'target_visit_id'],
     'visits': ['created_at',
                'department_id',
                'expected_payment_method',
                'facility_id',
                'id',
                'patient_id',
                'reason',
                'status',
                'visit_date',
                'visit_number']}
    for table_name in existing_tables:
        actual_columns = {column["name"] for column in inspector.get_columns(table_name)}
        missing_columns = set(required_columns[table_name]) - actual_columns
        if missing_columns:
            missing = sorted(missing_columns)
            raise RuntimeError(f"Refusing baseline migration; {table_name} is missing columns: {missing}")
    existing_indexes = {
        table_name: {index["name"] for index in inspector.get_indexes(table_name) if index.get("name")}
        for table_name in existing_tables
    }
    # ### commands auto generated by Alembic - please adjust! ###
    if 'facilities' not in existing_tables:
        op.create_table('facilities',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('name', sa.String(length=160), nullable=False),
        sa.Column('code', sa.String(length=12), nullable=False),
        sa.Column('currency', sa.String(length=3), nullable=False),
        sa.Column('timezone', sa.String(length=64), nullable=False),
        sa.Column('next_patient_number', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('code')
        )
    if 'job_runs' not in existing_tables:
        op.create_table('job_runs',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('name', sa.String(length=80), nullable=False),
        sa.Column('status', sa.String(length=16), nullable=False),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('processed_count', sa.Integer(), nullable=False),
        sa.Column('error', sa.String(length=160), nullable=True),
        sa.PrimaryKeyConstraint('id')
        )
    if 'ix_job_run_name_started' not in existing_indexes.get('job_runs', set()):
        op.create_index('ix_job_run_name_started', 'job_runs', ['name', 'started_at'], unique=False)
    if 'audit_events' not in existing_tables:
        op.create_table('audit_events',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('facility_id', sa.String(length=36), nullable=False),
        sa.Column('actor', sa.String(length=120), nullable=False),
        sa.Column('action', sa.String(length=64), nullable=False),
        sa.Column('entity_type', sa.String(length=64), nullable=False),
        sa.Column('entity_id', sa.String(length=36), nullable=False),
        sa.Column('details', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['facility_id'], ['facilities.id'], ),
        sa.PrimaryKeyConstraint('id')
        )
    if 'ix_audit_events_facility_id' not in existing_indexes.get('audit_events', set()):
        op.create_index(op.f('ix_audit_events_facility_id'), 'audit_events', ['facility_id'], unique=False)
    if 'departments' not in existing_tables:
        op.create_table('departments',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('facility_id', sa.String(length=36), nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('code', sa.String(length=12), nullable=False),
        sa.Column('type', sa.String(length=24), nullable=False),
        sa.Column('queue_prefix', sa.String(length=8), nullable=False),
        sa.Column('active', sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(['facility_id'], ['facilities.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('facility_id', 'code', name='uq_department_facility_code')
        )
    if 'ix_departments_facility_id' not in existing_indexes.get('departments', set()):
        op.create_index(op.f('ix_departments_facility_id'), 'departments', ['facility_id'], unique=False)
    if 'medication_stock_items' not in existing_tables:
        op.create_table('medication_stock_items',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('facility_id', sa.String(length=36), nullable=False),
        sa.Column('name', sa.String(length=160), nullable=False),
        sa.Column('strength', sa.String(length=80), nullable=False),
        sa.Column('form', sa.String(length=80), nullable=False),
        sa.Column('unit', sa.String(length=40), nullable=False),
        sa.Column('quantity_on_hand', sa.Integer(), nullable=False),
        sa.Column('reorder_level', sa.Integer(), nullable=False),
        sa.Column('unit_price', sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column('active', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint('quantity_on_hand >= 0', name='ck_medication_stock_nonnegative'),
        sa.CheckConstraint('reorder_level >= 0', name='ck_medication_stock_reorder_nonnegative'),
        sa.CheckConstraint('unit_price >= 0', name='ck_medication_stock_price_nonnegative'),
        sa.ForeignKeyConstraint(['facility_id'], ['facilities.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('facility_id', 'name', 'strength', 'form', name='uq_medication_stock_facility_product')
        )
    if 'ix_medication_stock_facility_active' not in existing_indexes.get('medication_stock_items', set()):
        op.create_index('ix_medication_stock_facility_active', 'medication_stock_items', ['facility_id', 'active', 'name'], unique=False)
    if 'ix_medication_stock_items_facility_id' not in existing_indexes.get('medication_stock_items', set()):
        op.create_index(op.f('ix_medication_stock_items_facility_id'), 'medication_stock_items', ['facility_id'], unique=False)
    if 'patients' not in existing_tables:
        op.create_table('patients',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('facility_id', sa.String(length=36), nullable=False),
        sa.Column('patient_number', sa.String(length=32), nullable=False),
        sa.Column('first_name', sa.String(length=80), nullable=False),
        sa.Column('last_name', sa.String(length=80), nullable=False),
        sa.Column('other_names', sa.String(length=120), nullable=True),
        sa.Column('sex', sa.String(length=24), nullable=False),
        sa.Column('date_of_birth', sa.Date(), nullable=True),
        sa.Column('estimated_age', sa.Integer(), nullable=True),
        sa.Column('phone', sa.String(length=32), nullable=True),
        sa.Column('alt_phone', sa.String(length=32), nullable=True),
        sa.Column('email', sa.String(length=254), nullable=True),
        sa.Column('national_id', sa.String(length=64), nullable=True),
        sa.Column('address', sa.String(length=240), nullable=True),
        sa.Column('next_of_kin_name', sa.String(length=160), nullable=True),
        sa.Column('next_of_kin_relationship', sa.String(length=80), nullable=True),
        sa.Column('next_of_kin_phone', sa.String(length=32), nullable=True),
        sa.Column('usual_payment_method', sa.String(length=24), nullable=False),
        sa.Column('allergies', sa.JSON(), nullable=False),
        sa.Column('sms_consent', sa.Boolean(), nullable=False),
        sa.Column('status', sa.String(length=16), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['facility_id'], ['facilities.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('facility_id', 'patient_number', name='uq_patient_facility_number')
        )
    if 'ix_patient_facility_name' not in existing_indexes.get('patients', set()):
        op.create_index('ix_patient_facility_name', 'patients', ['facility_id', 'last_name', 'first_name'], unique=False)
    if 'ix_patient_facility_phone' not in existing_indexes.get('patients', set()):
        op.create_index('ix_patient_facility_phone', 'patients', ['facility_id', 'phone'], unique=False)
    if 'ix_patients_facility_id' not in existing_indexes.get('patients', set()):
        op.create_index(op.f('ix_patients_facility_id'), 'patients', ['facility_id'], unique=False)
    if 'reminders' not in existing_tables:
        op.create_table('reminders',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('facility_id', sa.String(length=36), nullable=False),
        sa.Column('owner_id', sa.String(length=128), nullable=False),
        sa.Column('created_by', sa.String(length=128), nullable=False),
        sa.Column('title', sa.String(length=160), nullable=False),
        sa.Column('note', sa.String(length=500), nullable=True),
        sa.Column('link_type', sa.String(length=32), nullable=True),
        sa.Column('link_id', sa.String(length=128), nullable=True),
        sa.Column('due_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('timezone', sa.String(length=64), nullable=False),
        sa.Column('repeat_frequency', sa.String(length=16), nullable=False),
        sa.Column('repeat_interval', sa.Integer(), nullable=False),
        sa.Column('repeat_until', sa.DateTime(timezone=True), nullable=True),
        sa.Column('alert_offsets', sa.JSON(), nullable=False),
        sa.Column('priority', sa.String(length=16), nullable=False),
        sa.Column('status', sa.String(length=16), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['facility_id'], ['facilities.id'], ),
        sa.PrimaryKeyConstraint('id')
        )
    if 'ix_reminder_owner_status_due' not in existing_indexes.get('reminders', set()):
        op.create_index('ix_reminder_owner_status_due', 'reminders', ['owner_id', 'status', 'due_at'], unique=False)
    if 'ix_reminders_facility_id' not in existing_indexes.get('reminders', set()):
        op.create_index(op.f('ix_reminders_facility_id'), 'reminders', ['facility_id'], unique=False)
    if 'ix_reminders_owner_id' not in existing_indexes.get('reminders', set()):
        op.create_index(op.f('ix_reminders_owner_id'), 'reminders', ['owner_id'], unique=False)
    if 'support_requests' not in existing_tables:
        op.create_table('support_requests',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('facility_id', sa.String(length=36), nullable=False),
        sa.Column('ticket_number', sa.String(length=32), nullable=False),
        sa.Column('requester_id', sa.String(length=128), nullable=False),
        sa.Column('requester_role', sa.String(length=40), nullable=False),
        sa.Column('requester_name', sa.String(length=160), nullable=False),
        sa.Column('requester_email', sa.String(length=254), nullable=False),
        sa.Column('category', sa.String(length=32), nullable=False),
        sa.Column('subject', sa.String(length=120), nullable=False),
        sa.Column('message', sa.Text(), nullable=False),
        sa.Column('status', sa.String(length=16), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_by', sa.String(length=128), nullable=True),
        sa.ForeignKeyConstraint(['facility_id'], ['facilities.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('facility_id', 'ticket_number', name='uq_support_request_facility_ticket')
        )
    if 'ix_support_request_facility_requester_created' not in existing_indexes.get('support_requests', set()):
        op.create_index('ix_support_request_facility_requester_created', 'support_requests', ['facility_id', 'requester_id', 'created_at'], unique=False)
    if 'ix_support_request_facility_status_created' not in existing_indexes.get('support_requests', set()):
        op.create_index('ix_support_request_facility_status_created', 'support_requests', ['facility_id', 'status', 'created_at'], unique=False)
    if 'ix_support_requests_facility_id' not in existing_indexes.get('support_requests', set()):
        op.create_index(op.f('ix_support_requests_facility_id'), 'support_requests', ['facility_id'], unique=False)
    if 'appointments' not in existing_tables:
        op.create_table('appointments',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('facility_id', sa.String(length=36), nullable=False),
        sa.Column('patient_id', sa.String(length=36), nullable=False),
        sa.Column('department_id', sa.String(length=36), nullable=False),
        sa.Column('starts_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('ends_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('appointment_type', sa.String(length=32), nullable=False),
        sa.Column('clinician', sa.String(length=120), nullable=True),
        sa.Column('reason', sa.String(length=240), nullable=False),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('cancellation_reason', sa.String(length=240), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['department_id'], ['departments.id'], ),
        sa.ForeignKeyConstraint(['facility_id'], ['facilities.id'], ),
        sa.ForeignKeyConstraint(['patient_id'], ['patients.id'], ),
        sa.PrimaryKeyConstraint('id')
        )
    if 'ix_appointment_facility_start' not in existing_indexes.get('appointments', set()):
        op.create_index('ix_appointment_facility_start', 'appointments', ['facility_id', 'starts_at'], unique=False)
    if 'ix_appointments_department_id' not in existing_indexes.get('appointments', set()):
        op.create_index(op.f('ix_appointments_department_id'), 'appointments', ['department_id'], unique=False)
    if 'ix_appointments_facility_id' not in existing_indexes.get('appointments', set()):
        op.create_index(op.f('ix_appointments_facility_id'), 'appointments', ['facility_id'], unique=False)
    if 'ix_appointments_patient_id' not in existing_indexes.get('appointments', set()):
        op.create_index(op.f('ix_appointments_patient_id'), 'appointments', ['patient_id'], unique=False)
    if 'billing_invoices' not in existing_tables:
        op.create_table('billing_invoices',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('facility_id', sa.String(length=36), nullable=False),
        sa.Column('patient_id', sa.String(length=36), nullable=False),
        sa.Column('invoice_number', sa.String(length=32), nullable=False),
        sa.Column('description', sa.String(length=240), nullable=False),
        sa.Column('total_amount', sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column('status', sa.String(length=16), nullable=False),
        sa.Column('created_by', sa.String(length=128), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint('total_amount > 0', name='ck_billing_invoice_positive_total'),
        sa.ForeignKeyConstraint(['facility_id'], ['facilities.id'], ),
        sa.ForeignKeyConstraint(['patient_id'], ['patients.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('facility_id', 'invoice_number', name='uq_billing_invoice_facility_number')
        )
    if 'ix_billing_invoice_facility_status' not in existing_indexes.get('billing_invoices', set()):
        op.create_index('ix_billing_invoice_facility_status', 'billing_invoices', ['facility_id', 'status', 'created_at'], unique=False)
    if 'ix_billing_invoices_facility_id' not in existing_indexes.get('billing_invoices', set()):
        op.create_index(op.f('ix_billing_invoices_facility_id'), 'billing_invoices', ['facility_id'], unique=False)
    if 'ix_billing_invoices_patient_id' not in existing_indexes.get('billing_invoices', set()):
        op.create_index(op.f('ix_billing_invoices_patient_id'), 'billing_invoices', ['patient_id'], unique=False)
    if 'laboratory_orders' not in existing_tables:
        op.create_table('laboratory_orders',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('facility_id', sa.String(length=36), nullable=False),
        sa.Column('patient_id', sa.String(length=36), nullable=False),
        sa.Column('test_name', sa.String(length=160), nullable=False),
        sa.Column('specimen', sa.String(length=100), nullable=False),
        sa.Column('priority', sa.String(length=16), nullable=False),
        sa.Column('clinical_notes', sa.Text(), nullable=True),
        sa.Column('status', sa.String(length=16), nullable=False),
        sa.Column('result', sa.Text(), nullable=True),
        sa.Column('ordered_by', sa.String(length=128), nullable=False),
        sa.Column('resulted_by', sa.String(length=128), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('resulted_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['facility_id'], ['facilities.id'], ),
        sa.ForeignKeyConstraint(['patient_id'], ['patients.id'], ),
        sa.PrimaryKeyConstraint('id')
        )
    if 'ix_laboratory_order_facility_status' not in existing_indexes.get('laboratory_orders', set()):
        op.create_index('ix_laboratory_order_facility_status', 'laboratory_orders', ['facility_id', 'status', 'created_at'], unique=False)
    if 'ix_laboratory_orders_facility_id' not in existing_indexes.get('laboratory_orders', set()):
        op.create_index(op.f('ix_laboratory_orders_facility_id'), 'laboratory_orders', ['facility_id'], unique=False)
    if 'ix_laboratory_orders_patient_id' not in existing_indexes.get('laboratory_orders', set()):
        op.create_index(op.f('ix_laboratory_orders_patient_id'), 'laboratory_orders', ['patient_id'], unique=False)
    if 'medication_orders' not in existing_tables:
        op.create_table('medication_orders',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('facility_id', sa.String(length=36), nullable=False),
        sa.Column('patient_id', sa.String(length=36), nullable=False),
        sa.Column('stock_item_id', sa.String(length=36), nullable=False),
        sa.Column('dosage', sa.String(length=160), nullable=False),
        sa.Column('frequency', sa.String(length=160), nullable=False),
        sa.Column('duration', sa.String(length=100), nullable=True),
        sa.Column('quantity', sa.Integer(), nullable=False),
        sa.Column('instructions', sa.Text(), nullable=True),
        sa.Column('status', sa.String(length=16), nullable=False),
        sa.Column('prescribed_by', sa.String(length=128), nullable=False),
        sa.Column('dispensed_by', sa.String(length=128), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('dispensed_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['facility_id'], ['facilities.id'], ),
        sa.ForeignKeyConstraint(['patient_id'], ['patients.id'], ),
        sa.ForeignKeyConstraint(['stock_item_id'], ['medication_stock_items.id'], ),
        sa.PrimaryKeyConstraint('id')
        )
    if 'ix_medication_order_facility_status' not in existing_indexes.get('medication_orders', set()):
        op.create_index('ix_medication_order_facility_status', 'medication_orders', ['facility_id', 'status', 'created_at'], unique=False)
    if 'ix_medication_orders_facility_id' not in existing_indexes.get('medication_orders', set()):
        op.create_index(op.f('ix_medication_orders_facility_id'), 'medication_orders', ['facility_id'], unique=False)
    if 'ix_medication_orders_patient_id' not in existing_indexes.get('medication_orders', set()):
        op.create_index(op.f('ix_medication_orders_patient_id'), 'medication_orders', ['patient_id'], unique=False)
    if 'ix_medication_orders_stock_item_id' not in existing_indexes.get('medication_orders', set()):
        op.create_index(op.f('ix_medication_orders_stock_item_id'), 'medication_orders', ['stock_item_id'], unique=False)
    if 'medication_stock_batches' not in existing_tables:
        op.create_table('medication_stock_batches',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('facility_id', sa.String(length=36), nullable=False),
        sa.Column('stock_item_id', sa.String(length=36), nullable=False),
        sa.Column('batch_number', sa.String(length=100), nullable=False),
        sa.Column('expires_on', sa.Date(), nullable=False),
        sa.Column('quantity_received', sa.Integer(), nullable=False),
        sa.Column('quantity_remaining', sa.Integer(), nullable=False),
        sa.Column('received_by', sa.String(length=128), nullable=False),
        sa.Column('received_at', sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint('quantity_received > 0', name='ck_stock_batch_received_positive'),
        sa.CheckConstraint('quantity_remaining >= 0', name='ck_stock_batch_remaining_nonnegative'),
        sa.ForeignKeyConstraint(['facility_id'], ['facilities.id'], ),
        sa.ForeignKeyConstraint(['stock_item_id'], ['medication_stock_items.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('facility_id', 'stock_item_id', 'batch_number', name='uq_medication_stock_batch_number')
        )
    if 'ix_medication_stock_batches_facility_id' not in existing_indexes.get('medication_stock_batches', set()):
        op.create_index(op.f('ix_medication_stock_batches_facility_id'), 'medication_stock_batches', ['facility_id'], unique=False)
    if 'ix_medication_stock_batches_stock_item_id' not in existing_indexes.get('medication_stock_batches', set()):
        op.create_index(op.f('ix_medication_stock_batches_stock_item_id'), 'medication_stock_batches', ['stock_item_id'], unique=False)
    if 'ix_stock_batch_expiry' not in existing_indexes.get('medication_stock_batches', set()):
        op.create_index('ix_stock_batch_expiry', 'medication_stock_batches', ['facility_id', 'stock_item_id', 'expires_on'], unique=False)
    if 'medication_stock_movements' not in existing_tables:
        op.create_table('medication_stock_movements',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('facility_id', sa.String(length=36), nullable=False),
        sa.Column('stock_item_id', sa.String(length=36), nullable=False),
        sa.Column('movement_type', sa.String(length=16), nullable=False),
        sa.Column('quantity', sa.Integer(), nullable=False),
        sa.Column('reference', sa.String(length=240), nullable=True),
        sa.Column('created_by', sa.String(length=128), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['facility_id'], ['facilities.id'], ),
        sa.ForeignKeyConstraint(['stock_item_id'], ['medication_stock_items.id'], ),
        sa.PrimaryKeyConstraint('id')
        )
    if 'ix_medication_movement_facility_created' not in existing_indexes.get('medication_stock_movements', set()):
        op.create_index('ix_medication_movement_facility_created', 'medication_stock_movements', ['facility_id', 'created_at'], unique=False)
    if 'ix_medication_stock_movements_facility_id' not in existing_indexes.get('medication_stock_movements', set()):
        op.create_index(op.f('ix_medication_stock_movements_facility_id'), 'medication_stock_movements', ['facility_id'], unique=False)
    if 'ix_medication_stock_movements_stock_item_id' not in existing_indexes.get('medication_stock_movements', set()):
        op.create_index(op.f('ix_medication_stock_movements_stock_item_id'), 'medication_stock_movements', ['stock_item_id'], unique=False)
    if 'reminder_occurrences' not in existing_tables:
        op.create_table('reminder_occurrences',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('reminder_id', sa.String(length=36), nullable=False),
        sa.Column('fire_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('alert_offset_minutes', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(length=16), nullable=False),
        sa.Column('fired_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('snoozed_until', sa.DateTime(timezone=True), nullable=True),
        sa.Column('acknowledged_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['reminder_id'], ['reminders.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('reminder_id', 'fire_at', 'alert_offset_minutes', name='uq_reminder_occurrence_fire_offset')
        )
    if 'ix_reminder_occurrence_pending' not in existing_indexes.get('reminder_occurrences', set()):
        op.create_index('ix_reminder_occurrence_pending', 'reminder_occurrences', ['status', 'fire_at'], unique=False)
    if 'ix_reminder_occurrences_reminder_id' not in existing_indexes.get('reminder_occurrences', set()):
        op.create_index(op.f('ix_reminder_occurrences_reminder_id'), 'reminder_occurrences', ['reminder_id'], unique=False)
    if 'theatre_procedures' not in existing_tables:
        op.create_table('theatre_procedures',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('facility_id', sa.String(length=36), nullable=False),
        sa.Column('patient_id', sa.String(length=36), nullable=False),
        sa.Column('procedure_name', sa.String(length=160), nullable=False),
        sa.Column('scheduled_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('lead_clinician', sa.String(length=120), nullable=False),
        sa.Column('status', sa.String(length=16), nullable=False),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('created_by', sa.String(length=128), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['facility_id'], ['facilities.id'], ),
        sa.ForeignKeyConstraint(['patient_id'], ['patients.id'], ),
        sa.PrimaryKeyConstraint('id')
        )
    if 'ix_theatre_procedure_facility_status_time' not in existing_indexes.get('theatre_procedures', set()):
        op.create_index('ix_theatre_procedure_facility_status_time', 'theatre_procedures', ['facility_id', 'status', 'scheduled_at'], unique=False)
    if 'ix_theatre_procedures_facility_id' not in existing_indexes.get('theatre_procedures', set()):
        op.create_index(op.f('ix_theatre_procedures_facility_id'), 'theatre_procedures', ['facility_id'], unique=False)
    if 'ix_theatre_procedures_patient_id' not in existing_indexes.get('theatre_procedures', set()):
        op.create_index(op.f('ix_theatre_procedures_patient_id'), 'theatre_procedures', ['patient_id'], unique=False)
    if 'visits' not in existing_tables:
        op.create_table('visits',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('facility_id', sa.String(length=36), nullable=False),
        sa.Column('patient_id', sa.String(length=36), nullable=False),
        sa.Column('department_id', sa.String(length=36), nullable=False),
        sa.Column('visit_number', sa.String(length=32), nullable=False),
        sa.Column('visit_date', sa.DateTime(timezone=True), nullable=False),
        sa.Column('reason', sa.String(length=240), nullable=False),
        sa.Column('expected_payment_method', sa.String(length=24), nullable=False),
        sa.Column('status', sa.String(length=28), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['department_id'], ['departments.id'], ),
        sa.ForeignKeyConstraint(['facility_id'], ['facilities.id'], ),
        sa.ForeignKeyConstraint(['patient_id'], ['patients.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('facility_id', 'visit_number', name='uq_visit_facility_number')
        )
    if 'ix_visit_facility_status' not in existing_indexes.get('visits', set()):
        op.create_index('ix_visit_facility_status', 'visits', ['facility_id', 'status'], unique=False)
    if 'ix_visits_department_id' not in existing_indexes.get('visits', set()):
        op.create_index(op.f('ix_visits_department_id'), 'visits', ['department_id'], unique=False)
    if 'ix_visits_facility_id' not in existing_indexes.get('visits', set()):
        op.create_index(op.f('ix_visits_facility_id'), 'visits', ['facility_id'], unique=False)
    if 'ix_visits_patient_id' not in existing_indexes.get('visits', set()):
        op.create_index(op.f('ix_visits_patient_id'), 'visits', ['patient_id'], unique=False)
    if 'billing_invoice_details' not in existing_tables:
        op.create_table('billing_invoice_details',
        sa.Column('invoice_id', sa.String(length=36), nullable=False),
        sa.Column('bill_to_name', sa.String(length=160), nullable=True),
        sa.Column('bill_to_phone', sa.String(length=32), nullable=True),
        sa.Column('payer_type', sa.String(length=24), nullable=False),
        sa.Column('insurer_name', sa.String(length=160), nullable=True),
        sa.Column('payer_reference', sa.String(length=80), nullable=True),
        sa.Column('service_date', sa.Date(), nullable=True),
        sa.Column('due_date', sa.Date(), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['invoice_id'], ['billing_invoices.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('invoice_id')
        )
    if 'billing_invoice_lines' not in existing_tables:
        op.create_table('billing_invoice_lines',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('invoice_id', sa.String(length=36), nullable=False),
        sa.Column('position', sa.Integer(), nullable=False),
        sa.Column('description', sa.String(length=240), nullable=False),
        sa.Column('unit', sa.String(length=40), nullable=False),
        sa.Column('quantity', sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column('unit_price', sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column('amount', sa.Numeric(precision=12, scale=2), nullable=False),
        sa.CheckConstraint('amount > 0', name='ck_billing_invoice_line_amount_positive'),
        sa.CheckConstraint('quantity > 0', name='ck_billing_invoice_line_quantity_positive'),
        sa.CheckConstraint('unit_price > 0', name='ck_billing_invoice_line_price_positive'),
        sa.ForeignKeyConstraint(['invoice_id'], ['billing_invoices.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('invoice_id', 'position', name='uq_billing_invoice_line_position')
        )
    if 'ix_billing_invoice_lines_invoice_id' not in existing_indexes.get('billing_invoice_lines', set()):
        op.create_index(op.f('ix_billing_invoice_lines_invoice_id'), 'billing_invoice_lines', ['invoice_id'], unique=False)
    if 'billing_payments' not in existing_tables:
        op.create_table('billing_payments',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('facility_id', sa.String(length=36), nullable=False),
        sa.Column('invoice_id', sa.String(length=36), nullable=False),
        sa.Column('amount', sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column('method', sa.String(length=24), nullable=False),
        sa.Column('reference', sa.String(length=120), nullable=True),
        sa.Column('recorded_by', sa.String(length=128), nullable=False),
        sa.Column('paid_at', sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint('amount > 0', name='ck_billing_payment_positive_amount'),
        sa.ForeignKeyConstraint(['facility_id'], ['facilities.id'], ),
        sa.ForeignKeyConstraint(['invoice_id'], ['billing_invoices.id'], ),
        sa.PrimaryKeyConstraint('id')
        )
    if 'ix_billing_payment_invoice_paid' not in existing_indexes.get('billing_payments', set()):
        op.create_index('ix_billing_payment_invoice_paid', 'billing_payments', ['invoice_id', 'paid_at'], unique=False)
    if 'ix_billing_payments_facility_id' not in existing_indexes.get('billing_payments', set()):
        op.create_index(op.f('ix_billing_payments_facility_id'), 'billing_payments', ['facility_id'], unique=False)
    if 'ix_billing_payments_invoice_id' not in existing_indexes.get('billing_payments', set()):
        op.create_index(op.f('ix_billing_payments_invoice_id'), 'billing_payments', ['invoice_id'], unique=False)
    if 'insurance_claims' not in existing_tables:
        op.create_table('insurance_claims',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('facility_id', sa.String(length=36), nullable=False),
        sa.Column('invoice_id', sa.String(length=36), nullable=False),
        sa.Column('claim_number', sa.String(length=32), nullable=False),
        sa.Column('status', sa.String(length=16), nullable=False),
        sa.Column('external_claim_reference', sa.String(length=120), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('created_by', sa.String(length=128), nullable=False),
        sa.Column('updated_by', sa.String(length=128), nullable=True),
        sa.Column('submitted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['facility_id'], ['facilities.id'], ),
        sa.ForeignKeyConstraint(['invoice_id'], ['billing_invoices.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('facility_id', 'claim_number', name='uq_insurance_claim_facility_number'),
        sa.UniqueConstraint('invoice_id', name='uq_insurance_claim_invoice')
        )
    if 'ix_insurance_claim_facility_status' not in existing_indexes.get('insurance_claims', set()):
        op.create_index('ix_insurance_claim_facility_status', 'insurance_claims', ['facility_id', 'status', 'created_at'], unique=False)
    if 'ix_insurance_claims_facility_id' not in existing_indexes.get('insurance_claims', set()):
        op.create_index(op.f('ix_insurance_claims_facility_id'), 'insurance_claims', ['facility_id'], unique=False)
    if 'ix_insurance_claims_invoice_id' not in existing_indexes.get('insurance_claims', set()):
        op.create_index(op.f('ix_insurance_claims_invoice_id'), 'insurance_claims', ['invoice_id'], unique=False)
    if 'laboratory_result_reviews' not in existing_tables:
        op.create_table('laboratory_result_reviews',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('facility_id', sa.String(length=36), nullable=False),
        sa.Column('order_id', sa.String(length=36), nullable=False),
        sa.Column('reviewed_by', sa.String(length=128), nullable=False),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('reviewed_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['facility_id'], ['facilities.id'], ),
        sa.ForeignKeyConstraint(['order_id'], ['laboratory_orders.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
        )
    if 'ix_laboratory_result_reviews_facility_id' not in existing_indexes.get('laboratory_result_reviews', set()):
        op.create_index(op.f('ix_laboratory_result_reviews_facility_id'), 'laboratory_result_reviews', ['facility_id'], unique=False)
    if 'ix_laboratory_result_reviews_order_id' not in existing_indexes.get('laboratory_result_reviews', set()):
        op.create_index(op.f('ix_laboratory_result_reviews_order_id'), 'laboratory_result_reviews', ['order_id'], unique=True)
    if 'laboratory_samples' not in existing_tables:
        op.create_table('laboratory_samples',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('facility_id', sa.String(length=36), nullable=False),
        sa.Column('order_id', sa.String(length=36), nullable=False),
        sa.Column('status', sa.String(length=24), nullable=False),
        sa.Column('collected_by', sa.String(length=128), nullable=True),
        sa.Column('collected_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('updated_by', sa.String(length=128), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['facility_id'], ['facilities.id'], ),
        sa.ForeignKeyConstraint(['order_id'], ['laboratory_orders.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
        )
    if 'ix_laboratory_samples_facility_id' not in existing_indexes.get('laboratory_samples', set()):
        op.create_index(op.f('ix_laboratory_samples_facility_id'), 'laboratory_samples', ['facility_id'], unique=False)
    if 'ix_laboratory_samples_order_id' not in existing_indexes.get('laboratory_samples', set()):
        op.create_index(op.f('ix_laboratory_samples_order_id'), 'laboratory_samples', ['order_id'], unique=True)
    if 'notifications' not in existing_tables:
        op.create_table('notifications',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('facility_id', sa.String(length=36), nullable=False),
        sa.Column('recipient_user_id', sa.String(length=128), nullable=False),
        sa.Column('reminder_occurrence_id', sa.String(length=36), nullable=True),
        sa.Column('type', sa.String(length=48), nullable=False),
        sa.Column('title', sa.String(length=160), nullable=False),
        sa.Column('body', sa.String(length=500), nullable=False),
        sa.Column('link_type', sa.String(length=32), nullable=True),
        sa.Column('link_id', sa.String(length=128), nullable=True),
        sa.Column('priority', sa.String(length=16), nullable=False),
        sa.Column('status', sa.String(length=16), nullable=False),
        sa.Column('snoozed_until', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('read_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['facility_id'], ['facilities.id'], ),
        sa.ForeignKeyConstraint(['reminder_occurrence_id'], ['reminder_occurrences.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('reminder_occurrence_id')
        )
    if 'ix_notification_recipient_status_created' not in existing_indexes.get('notifications', set()):
        op.create_index('ix_notification_recipient_status_created', 'notifications', ['recipient_user_id', 'status', 'created_at'], unique=False)
    if 'ix_notifications_facility_id' not in existing_indexes.get('notifications', set()):
        op.create_index(op.f('ix_notifications_facility_id'), 'notifications', ['facility_id'], unique=False)
    if 'ix_notifications_recipient_user_id' not in existing_indexes.get('notifications', set()):
        op.create_index(op.f('ix_notifications_recipient_user_id'), 'notifications', ['recipient_user_id'], unique=False)
    if 'queue_entries' not in existing_tables:
        op.create_table('queue_entries',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('facility_id', sa.String(length=36), nullable=False),
        sa.Column('visit_id', sa.String(length=36), nullable=False),
        sa.Column('department_id', sa.String(length=36), nullable=False),
        sa.Column('queue_number', sa.String(length=20), nullable=False),
        sa.Column('queue_date', sa.Date(), nullable=False),
        sa.Column('priority', sa.String(length=16), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('arrived_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('called_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('called_by', sa.String(length=120), nullable=True),
        sa.ForeignKeyConstraint(['department_id'], ['departments.id'], ),
        sa.ForeignKeyConstraint(['facility_id'], ['facilities.id'], ),
        sa.ForeignKeyConstraint(['visit_id'], ['visits.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('facility_id', 'department_id', 'queue_number', 'queue_date', name='uq_queue_daily_number'),
        sa.UniqueConstraint('visit_id')
        )
    if 'ix_queue_entries_department_id' not in existing_indexes.get('queue_entries', set()):
        op.create_index(op.f('ix_queue_entries_department_id'), 'queue_entries', ['department_id'], unique=False)
    if 'ix_queue_entries_facility_id' not in existing_indexes.get('queue_entries', set()):
        op.create_index(op.f('ix_queue_entries_facility_id'), 'queue_entries', ['facility_id'], unique=False)
    if 'ix_queue_waiting' not in existing_indexes.get('queue_entries', set()):
        op.create_index('ix_queue_waiting', 'queue_entries', ['facility_id', 'department_id', 'status', 'priority', 'arrived_at'], unique=False)
    if 'triage_records' not in existing_tables:
        op.create_table('triage_records',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('facility_id', sa.String(length=36), nullable=False),
        sa.Column('visit_id', sa.String(length=36), nullable=False),
        sa.Column('temperature', sa.Float(), nullable=True),
        sa.Column('pulse', sa.Integer(), nullable=True),
        sa.Column('respiratory_rate', sa.Integer(), nullable=True),
        sa.Column('systolic', sa.Integer(), nullable=True),
        sa.Column('diastolic', sa.Integer(), nullable=True),
        sa.Column('spo2', sa.Integer(), nullable=True),
        sa.Column('weight', sa.Float(), nullable=True),
        sa.Column('height', sa.Float(), nullable=True),
        sa.Column('bmi', sa.Float(), nullable=True),
        sa.Column('pain_score', sa.Integer(), nullable=True),
        sa.Column('blood_sugar', sa.Float(), nullable=True),
        sa.Column('priority', sa.String(length=16), nullable=False),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('recorded_by', sa.String(length=120), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['facility_id'], ['facilities.id'], ),
        sa.ForeignKeyConstraint(['visit_id'], ['visits.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('visit_id')
        )
    if 'ix_triage_records_facility_id' not in existing_indexes.get('triage_records', set()):
        op.create_index(op.f('ix_triage_records_facility_id'), 'triage_records', ['facility_id'], unique=False)
    if 'visit_handoffs' not in existing_tables:
        op.create_table('visit_handoffs',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('facility_id', sa.String(length=36), nullable=False),
        sa.Column('source_visit_id', sa.String(length=36), nullable=False),
        sa.Column('target_visit_id', sa.String(length=36), nullable=False),
        sa.Column('source_department_id', sa.String(length=36), nullable=False),
        sa.Column('target_department_id', sa.String(length=36), nullable=False),
        sa.Column('reason', sa.String(length=240), nullable=False),
        sa.Column('created_by', sa.String(length=128), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['facility_id'], ['facilities.id'], ),
        sa.ForeignKeyConstraint(['source_department_id'], ['departments.id'], ),
        sa.ForeignKeyConstraint(['source_visit_id'], ['visits.id'], ),
        sa.ForeignKeyConstraint(['target_department_id'], ['departments.id'], ),
        sa.ForeignKeyConstraint(['target_visit_id'], ['visits.id'], ),
        sa.PrimaryKeyConstraint('id')
        )
    if 'ix_visit_handoffs_facility_id' not in existing_indexes.get('visit_handoffs', set()):
        op.create_index(op.f('ix_visit_handoffs_facility_id'), 'visit_handoffs', ['facility_id'], unique=False)
    if 'ix_visit_handoffs_source_visit_id' not in existing_indexes.get('visit_handoffs', set()):
        op.create_index(op.f('ix_visit_handoffs_source_visit_id'), 'visit_handoffs', ['source_visit_id'], unique=False)
    if 'ix_visit_handoffs_target_visit_id' not in existing_indexes.get('visit_handoffs', set()):
        op.create_index(op.f('ix_visit_handoffs_target_visit_id'), 'visit_handoffs', ['target_visit_id'], unique=True)
    if 'billing_payment_receipts' not in existing_tables:
        op.create_table('billing_payment_receipts',
        sa.Column('payment_id', sa.String(length=36), nullable=False),
        sa.Column('facility_id', sa.String(length=36), nullable=False),
        sa.Column('receipt_number', sa.String(length=32), nullable=False),
        sa.Column('issued_by', sa.String(length=128), nullable=False),
        sa.Column('issued_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['facility_id'], ['facilities.id'], ),
        sa.ForeignKeyConstraint(['payment_id'], ['billing_payments.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('payment_id'),
        sa.UniqueConstraint('facility_id', 'receipt_number', name='uq_billing_receipt_facility_number')
        )
    if 'ix_billing_payment_receipts_facility_id' not in existing_indexes.get('billing_payment_receipts', set()):
        op.create_index(op.f('ix_billing_payment_receipts_facility_id'), 'billing_payment_receipts', ['facility_id'], unique=False)
    # ### end Alembic commands ###


def downgrade() -> None:
    raise RuntimeError("The initial schema baseline cannot be automatically downgraded; restore a verified backup instead.")
