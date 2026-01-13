package main

import (
	"context"
	"database/sql"
	"encoding/json"
	"fmt"
	"log"
	"strings"
	"time"

	_ "github.com/lib/pq" // PostgreSQL driver
)

// DB wraps the database connection
type DB struct {
	conn *sql.DB
}

// InitDB initializes the database connection
func InitDB(connStr string) (*DB, error) {
	db, err := sql.Open("postgres", connStr)
	if err != nil {
		return nil, fmt.Errorf("failed to open database: %w", err)
	}

	// Configure connection pool
	db.SetMaxOpenConns(25)
	db.SetMaxIdleConns(5)
	db.SetConnMaxLifetime(5 * time.Minute)

	// Test connection with timeout
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()

	if err := db.PingContext(ctx); err != nil {
		return nil, fmt.Errorf("failed to ping database: %w", err)
	}

	log.Println("Database connection established successfully")
	return &DB{conn: db}, nil
}

// InitSchema initializes the database schema
func InitSchema(db *DB) error {
	schema := `
	CREATE TABLE IF NOT EXISTS apps (
		id SERIAL PRIMARY KEY,
		app_name VARCHAR(255) NOT NULL UNIQUE,
		username VARCHAR(255) NOT NULL,
		user_home_directory TEXT NOT NULL,
		dockerfile TEXT NOT NULL,
		port INTEGER NOT NULL,
		optional_features JSONB DEFAULT '[]'::jsonb,
		strip_prefix BOOLEAN DEFAULT FALSE,
		status VARCHAR(20) NOT NULL DEFAULT 'pending',
		created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
		updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
	);

	CREATE INDEX IF NOT EXISTS idx_apps_app_name ON apps(app_name);
	CREATE INDEX IF NOT EXISTS idx_apps_username ON apps(username);

	-- Add strip_prefix column if it doesn't exist (for existing databases)
	ALTER TABLE apps ADD COLUMN IF NOT EXISTS strip_prefix BOOLEAN DEFAULT FALSE;
	`

	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()

	_, err := db.conn.ExecContext(ctx, schema)
	if err != nil {
		return fmt.Errorf("failed to initialize schema: %w", err)
	}

	log.Println("Database schema initialized successfully")
	return nil
}

// CreateApp creates a new app in the database
func (db *DB) CreateApp(ctx context.Context, req *AppCreateRequest) (*App, error) {
	query := `
		INSERT INTO apps (app_name, username, user_home_directory, dockerfile, port, optional_features, strip_prefix, status)
		VALUES ($1, $2, $3, $4, $5, $6, $7, 'pending')
		RETURNING id, app_name, username, user_home_directory, dockerfile, port, optional_features, strip_prefix, status, created_at, updated_at
	`

	// Marshal optional_features to JSON
	featuresJSON, err := json.Marshal(req.OptionalFeatures)
	if err != nil {
		return nil, fmt.Errorf("failed to marshal optional_features: %w", err)
	}

	var app App
	var featuresStr string

	err = db.conn.QueryRowContext(ctx, query,
		req.AppName,
		req.Username,
		req.UserHomeDirectory,
		req.Dockerfile,
		req.Port,
		featuresJSON,
		req.StripPrefix,
	).Scan(
		&app.ID,
		&app.AppName,
		&app.Username,
		&app.UserHomeDirectory,
		&app.Dockerfile,
		&app.Port,
		&featuresStr,
		&app.StripPrefix,
		&app.Status,
		&app.CreatedAt,
		&app.UpdatedAt,
	)

	if err != nil {
		// Check for duplicate key error
		if strings.Contains(err.Error(), "duplicate key") || strings.Contains(err.Error(), "unique constraint") {
			return nil, fmt.Errorf("app_name '%s' already exists", req.AppName)
		}
		return nil, fmt.Errorf("failed to create app: %w", err)
	}

	// Unmarshal optional_features from JSON
	if err := json.Unmarshal([]byte(featuresStr), &app.OptionalFeatures); err != nil {
		return nil, fmt.Errorf("failed to unmarshal optional_features: %w", err)
	}

	return &app, nil
}

// GetApp retrieves a single app by ID
func (db *DB) GetApp(ctx context.Context, id int) (*App, error) {
	query := `
		SELECT id, app_name, username, user_home_directory, dockerfile, port, optional_features, strip_prefix, status, created_at, updated_at
		FROM apps
		WHERE id = $1
	`

	var app App
	var featuresStr string

	err := db.conn.QueryRowContext(ctx, query, id).Scan(
		&app.ID,
		&app.AppName,
		&app.Username,
		&app.UserHomeDirectory,
		&app.Dockerfile,
		&app.Port,
		&featuresStr,
		&app.StripPrefix,
		&app.Status,
		&app.CreatedAt,
		&app.UpdatedAt,
	)

	if err == sql.ErrNoRows {
		return nil, fmt.Errorf("app not found")
	}
	if err != nil {
		return nil, fmt.Errorf("failed to get app: %w", err)
	}

	// Unmarshal optional_features from JSON
	if err := json.Unmarshal([]byte(featuresStr), &app.OptionalFeatures); err != nil {
		return nil, fmt.Errorf("failed to unmarshal optional_features: %w", err)
	}

	return &app, nil
}

// ListApps retrieves all apps from the database
func (db *DB) ListApps(ctx context.Context) ([]*App, error) {
	query := `
		SELECT id, app_name, username, user_home_directory, dockerfile, port, optional_features, strip_prefix, status, created_at, updated_at
		FROM apps
		ORDER BY created_at DESC
	`

	rows, err := db.conn.QueryContext(ctx, query)
	if err != nil {
		return nil, fmt.Errorf("failed to list apps: %w", err)
	}
	defer rows.Close()

	var apps []*App

	for rows.Next() {
		var app App
		var featuresStr string

		err := rows.Scan(
			&app.ID,
			&app.AppName,
			&app.Username,
			&app.UserHomeDirectory,
			&app.Dockerfile,
			&app.Port,
			&featuresStr,
			&app.StripPrefix,
			&app.Status,
			&app.CreatedAt,
			&app.UpdatedAt,
		)
		if err != nil {
			return nil, fmt.Errorf("failed to scan app: %w", err)
		}

		// Unmarshal optional_features from JSON
		if err := json.Unmarshal([]byte(featuresStr), &app.OptionalFeatures); err != nil {
			return nil, fmt.Errorf("failed to unmarshal optional_features: %w", err)
		}

		apps = append(apps, &app)
	}

	if err = rows.Err(); err != nil {
		return nil, fmt.Errorf("error iterating rows: %w", err)
	}

	return apps, nil
}

// UpdateApp updates an existing app
func (db *DB) UpdateApp(ctx context.Context, id int, req *AppCreateRequest) (*App, error) {
	query := `
		UPDATE apps
		SET app_name = $1, username = $2, user_home_directory = $3, dockerfile = $4, port = $5, optional_features = $6, strip_prefix = $7, updated_at = CURRENT_TIMESTAMP
		WHERE id = $8
		RETURNING id, app_name, username, user_home_directory, dockerfile, port, optional_features, strip_prefix, status, created_at, updated_at
	`

	// Marshal optional_features to JSON
	featuresJSON, err := json.Marshal(req.OptionalFeatures)
	if err != nil {
		return nil, fmt.Errorf("failed to marshal optional_features: %w", err)
	}

	var app App
	var featuresStr string

	err = db.conn.QueryRowContext(ctx, query,
		req.AppName,
		req.Username,
		req.UserHomeDirectory,
		req.Dockerfile,
		req.Port,
		featuresJSON,
		req.StripPrefix,
		id,
	).Scan(
		&app.ID,
		&app.AppName,
		&app.Username,
		&app.UserHomeDirectory,
		&app.Dockerfile,
		&app.Port,
		&featuresStr,
		&app.StripPrefix,
		&app.Status,
		&app.CreatedAt,
		&app.UpdatedAt,
	)

	if err == sql.ErrNoRows {
		return nil, fmt.Errorf("app not found")
	}
	if err != nil {
		// Check for duplicate key error
		if strings.Contains(err.Error(), "duplicate key") || strings.Contains(err.Error(), "unique constraint") {
			return nil, fmt.Errorf("app_name '%s' already exists", req.AppName)
		}
		return nil, fmt.Errorf("failed to update app: %w", err)
	}

	// Unmarshal optional_features from JSON
	if err := json.Unmarshal([]byte(featuresStr), &app.OptionalFeatures); err != nil {
		return nil, fmt.Errorf("failed to unmarshal optional_features: %w", err)
	}

	return &app, nil
}

// DeleteApp deletes an app by ID
func (db *DB) DeleteApp(ctx context.Context, id int) error {
	query := `DELETE FROM apps WHERE id = $1`

	result, err := db.conn.ExecContext(ctx, query, id)
	if err != nil {
		return fmt.Errorf("failed to delete app: %w", err)
	}

	rowsAffected, err := result.RowsAffected()
	if err != nil {
		return fmt.Errorf("failed to get rows affected: %w", err)
	}

	if rowsAffected == 0 {
		return fmt.Errorf("app not found")
	}

	return nil
}

// UpdateAppStatus updates the status of an app
func (db *DB) UpdateAppStatus(ctx context.Context, appID int, status string) error {
	query := `UPDATE apps SET status = $1, updated_at = CURRENT_TIMESTAMP WHERE id = $2`
	_, err := db.conn.ExecContext(ctx, query, status, appID)
	if err != nil {
		return fmt.Errorf("failed to update app status: %w", err)
	}
	return nil
}

// Close closes the database connection
func (db *DB) Close() error {
	return db.conn.Close()
}
