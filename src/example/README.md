# Workbench Example App

An example app template showing the basic structure for a Workbench custom app. This template demonstrates how to use template variables to make your app configurable.

## Template Variables

This example uses template variables (`${templateOption:*}`) to make the app configurable. When users create a custom app from this template in the Workbench UI, they can customize these values:

| Option | Description | Type | Default Value |
|-----|-----|-----|-----|
| image | Docker image to use for the application | string | quay.io/jupyter/base-notebook |
| port | Port the application exposes | string | 8888 |
| username | Default user inside the container | string | jovyan |
| homeDir | Home directory for the user (where cloud storage and repos are mounted) | string | /home/jovyan |
| cloud | Cloud provider | string | gcp |

## Key Concepts

- **Template variables** are replaced when the app is created
- **Home directory** is where Workbench mounts cloud storage buckets (`${homeDir}/workspaces`) and GitHub repos (`${homeDir}/repos`)
- **Port** must be exposed on the bridge network for Workbench to reach the app
- **Username** determines the identity inside the container

## Using This Template

You can generate a similar app structure using the script:

```bash
./scripts/create-custom-app.sh my-app jupyter/base-notebook 8888 jovyan /home/jovyan
```

---

_Note: This file was auto-generated from the [devcontainer-template.json](devcontainer-template.json).  Add additional notes to a `NOTES.md`._
