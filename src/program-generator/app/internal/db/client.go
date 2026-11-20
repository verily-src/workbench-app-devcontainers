package db

import (
	"database/sql"
	"fmt"
	"time"

	_ "github.com/lib/pq"
)

type Client struct {
	db *sql.DB
}

type Template struct {
	ID        int       `json:"id"`
	Name      string    `json:"name"`
	Yaml      string    `json:"yaml"`
	CreatedAt time.Time `json:"created_at"`
}

func NewClient(connStr string) (*Client, error) {
	db, err := sql.Open("postgres", connStr)
	if err != nil {
		return nil, fmt.Errorf("opening database: %w", err)
	}
	db.SetMaxOpenConns(10)
	db.SetMaxIdleConns(3)
	db.SetConnMaxLifetime(5 * time.Minute)

	if err := db.Ping(); err != nil {
		return nil, fmt.Errorf("pinging database: %w", err)
	}
	return &Client{db: db}, nil
}

func (c *Client) InitSchema() error {
	_, err := c.db.Exec(`
		CREATE TABLE IF NOT EXISTS templates (
			id SERIAL PRIMARY KEY,
			name VARCHAR(255) NOT NULL,
			yaml TEXT NOT NULL,
			created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
		);
		CREATE INDEX IF NOT EXISTS idx_templates_name ON templates(name);
	`)
	return err
}

func (c *Client) SaveTemplate(name, yaml string) (*Template, error) {
	var t Template
	err := c.db.QueryRow(
		`INSERT INTO templates (name, yaml) VALUES ($1, $2) RETURNING id, name, yaml, created_at`,
		name, yaml,
	).Scan(&t.ID, &t.Name, &t.Yaml, &t.CreatedAt)
	if err != nil {
		return nil, err
	}
	return &t, nil
}

func (c *Client) ListTemplates() ([]Template, error) {
	rows, err := c.db.Query(`SELECT id, name, yaml, created_at FROM templates ORDER BY created_at DESC LIMIT 50`)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	var templates []Template
	for rows.Next() {
		var t Template
		if err := rows.Scan(&t.ID, &t.Name, &t.Yaml, &t.CreatedAt); err != nil {
			return nil, err
		}
		templates = append(templates, t)
	}
	return templates, nil
}

func (c *Client) GetTemplate(id int) (*Template, error) {
	var t Template
	err := c.db.QueryRow(
		`SELECT id, name, yaml, created_at FROM templates WHERE id = $1`, id,
	).Scan(&t.ID, &t.Name, &t.Yaml, &t.CreatedAt)
	if err != nil {
		return nil, err
	}
	return &t, nil
}

func (c *Client) Ping() error {
	return c.db.Ping()
}

func (c *Client) Close() {
	c.db.Close()
}
