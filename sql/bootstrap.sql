-- Bootstrap Axiom tables in Unity Catalog.
-- Run this once if the app service principal lacks DDL privileges.
-- Replace `main` and `axiom` below for the target workspace before running.
CREATE SCHEMA IF NOT EXISTS main.axiom;
CREATE TABLE IF NOT EXISTS main.axiom.user_roles (
    email STRING NOT NULL,
    role STRING NOT NULL COMMENT 'reader | writer | admin',
    updated_at TIMESTAMP,
    updated_by STRING
) USING DELTA;
CREATE TABLE IF NOT EXISTS main.axiom.glossary_terms (
    term_id STRING NOT NULL,
    name STRING NOT NULL,
    definition STRING,
    domain STRING,
    owner_email STRING,
    status STRING COMMENT 'draft | approved | deprecated',
    created_at TIMESTAMP,
    created_by STRING,
    updated_at TIMESTAMP,
    updated_by STRING
) USING DELTA;
CREATE TABLE IF NOT EXISTS main.axiom.glossary_term_links (
    link_id STRING NOT NULL,
    term_id STRING NOT NULL,
    subject_type STRING NOT NULL COMMENT 'asset | column',
    subject_fqn STRING NOT NULL,
    column_name STRING,
    is_primary BOOLEAN,
    source STRING COMMENT 'manual | uc_tag | migration',
    source_value STRING,
    resolution_state STRING COMMENT 'linked | unresolved | retired',
    created_at TIMESTAMP,
    created_by STRING,
    updated_at TIMESTAMP,
    updated_by STRING,
    removed_at TIMESTAMP,
    removed_by STRING
) USING DELTA;
CREATE TABLE IF NOT EXISTS main.axiom.data_owners (
    uc_full_name STRING NOT NULL COMMENT 'catalog.schema.table',
    owner_email STRING NOT NULL,
    owner_type STRING COMMENT 'technical | business | steward',
    updated_at TIMESTAMP,
    updated_by STRING
) USING DELTA;
CREATE TABLE IF NOT EXISTS main.axiom.change_requests (
    request_id STRING NOT NULL,
    created_at TIMESTAMP,
    created_by STRING,
    status STRING COMMENT 'pending | approved | rejected',
    uc_full_name STRING,
    new_comment STRING,
    new_uc_tags_json STRING,
    reviewed_at TIMESTAMP,
    reviewed_by STRING,
    review_note STRING
) USING DELTA;
