//go:build linux

package main

import (
	"encoding/json"
	"fmt"
	"os"
	"os/exec"
	"strings"

	"golang.org/x/sys/unix"
)

// Linux pipe buffer capacity; writes up to this size complete without blocking.
const maxPipeSecretSize = 65536

const (
	SecretTypePipeVar = "pipeVar"
	SecretTypePathVar = "pathVar"
	SecretTypeValueVar = "valueVar"
)

type Secret struct {
	Type   string `json:"type"`
	Value  string `json:"value"`
	Target string `json:"target"`
}

func getSecrets() ([]Secret, error) {
	pipePath := "/tmp/secrets"
	if err := unix.Mkfifo(pipePath, 0600); err != nil {
		return nil, err
	}
	defer os.Remove(pipePath)

	fmt.Printf("Waiting for secrets to be written to named pipe at %s...\n", pipePath)
	file, err := os.OpenFile(pipePath, os.O_RDONLY, os.ModeNamedPipe)
	if err != nil {
		return nil, err
	}
	defer file.Close()

	var secrets []Secret
	decoder := json.NewDecoder(file)
	if err := decoder.Decode(&secrets); err != nil {
		return nil, err
	}

	return secrets, nil
}

func writeSecretToPipe(secret Secret) (string, error) {
	if len(secret.Value) > maxPipeSecretSize {
		return "", fmt.Errorf("secret for %s exceeds pipe buffer size (%d > %d)", secret.Target, len(secret.Value), maxPipeSecretSize)
	}

	fds := make([]int, 2)
	if err := unix.Pipe(fds); err != nil {
		return "", err
	}
	readFd, writeFd := fds[0], fds[1]

	if _, err := unix.Write(writeFd, []byte(secret.Value)); err != nil {
		unix.Close(readFd)
		unix.Close(writeFd)
		return "", err
	}
	unix.Close(writeFd)

	return fmt.Sprintf("/dev/fd/%d", readFd), nil
}

func writeSecretToMemfd(secret Secret) (path string, err error) {
	fd, err := unix.MemfdCreate(secret.Target, 0)
	if err != nil {
		return "", err
	}
	defer func() {
		if err != nil {
			unix.Close(fd)
		}
	}()

	if _, err = unix.Write(fd, []byte(secret.Value)); err != nil {
		return "", err
	}

	if _, err = unix.Seek(fd, 0, unix.SEEK_SET); err != nil {
		return "", err
	}

	return fmt.Sprintf("/dev/fd/%d", fd), nil
}

func buildSecretEnvVars(secrets []Secret) ([]string, error) {
	var envVars []string
	for _, secret := range secrets {
		switch secret.Type {
		case SecretTypePipeVar:
			secretPath, err := writeSecretToPipe(secret)
			if err != nil {
				return nil, fmt.Errorf("writing secret to pipe for %s: %w", secret.Target, err)
			}
			envVars = append(envVars, fmt.Sprintf("%s=%s", secret.Target, secretPath))
		case SecretTypePathVar:
			secretPath, err := writeSecretToMemfd(secret)
			if err != nil {
				return nil, fmt.Errorf("writing secret to memfd for %s: %w", secret.Target, err)
			}
			envVars = append(envVars, fmt.Sprintf("%s=%s", secret.Target, secretPath))
		case SecretTypeValueVar:
			envVars = append(envVars, fmt.Sprintf("%s=%s", secret.Target, secret.Value))
		default:
			return nil, fmt.Errorf("unknown secret type %s for target %s", secret.Type, secret.Target)
		}
	}

	return envVars, nil
}

func usage() {
	fmt.Fprintf(os.Stderr, "Usage: %s <command> [args...]\n", os.Args[0])
	os.Exit(1)
}

func main() {
	// Retrieve subcommand and arguments
	args := os.Args[1:]
	if len(args) < 1 {
		usage()
	}

	// Validate command before waiting for secrets
	if strings.Contains(args[0], " ") {
		args = append([]string{"sh", "-c"}, args...)
	}

	cmdPath, err := exec.LookPath(args[0])
	if err != nil {
		fmt.Fprintf(os.Stderr, "Error finding command %s: %v\n", args[0], err)
		os.Exit(1)
	}
	args[0] = cmdPath

	// Get secrets from named pipe
	secrets, err := getSecrets()
	if err != nil {
		fmt.Fprintf(os.Stderr, "Error getting secrets: %v\n", err)
		os.Exit(1)
	}

	secretEnvVars, err := buildSecretEnvVars(secrets)
	if err != nil {
		fmt.Fprintf(os.Stderr, "Error building secret env vars: %v\n", err)
		os.Exit(1)
	}

	// Replace current process with the specified command
	env := append(os.Environ(), secretEnvVars...)
	if err := unix.Exec(cmdPath, args, env); err != nil {
		fmt.Fprintf(os.Stderr, "Error executing command: %v\n", err)
		os.Exit(1)
	}
}
