package seeder

import (
	"context"
	"fmt"

	"cloud.google.com/go/storage"
)

// GCSClient uploads objects to Google Cloud Storage.
type GCSClient struct {
	client *storage.Client
}

// NewGCSClient creates a GCS client using application-default credentials.
func NewGCSClient(ctx context.Context) (*GCSClient, error) {
	client, err := storage.NewClient(ctx)
	if err != nil {
		return nil, fmt.Errorf("creating GCS client: %w", err)
	}
	return &GCSClient{client: client}, nil
}

// UploadPDF writes a PDF document to the specified GCS bucket and returns
// the public URL in the format expected by the consent backend:
//
//	https://storage.googleapis.com/{bucket}/{objectPath}
func (g *GCSClient) UploadPDF(ctx context.Context, bucket, objectPath string, pdfBytes []byte) (string, error) {
	obj := g.client.Bucket(bucket).Object(objectPath)
	writer := obj.NewWriter(ctx)
	writer.ContentType = "application/pdf"
	writer.CacheControl = "public, max-age=86400" // 1 day

	if _, err := writer.Write(pdfBytes); err != nil {
		writer.Close()
		return "", fmt.Errorf("writing PDF to GCS gs://%s/%s: %w", bucket, objectPath, err)
	}
	if err := writer.Close(); err != nil {
		return "", fmt.Errorf("finalizing GCS upload gs://%s/%s: %w", bucket, objectPath, err)
	}

	gcsURL := fmt.Sprintf("https://storage.googleapis.com/%s/%s", bucket, objectPath)
	return gcsURL, nil
}

// Close releases the GCS client's resources.
func (g *GCSClient) Close() {
	g.client.Close()
}
