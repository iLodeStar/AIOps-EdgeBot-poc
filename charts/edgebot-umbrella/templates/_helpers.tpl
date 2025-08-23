{{/*
Expand the name of the chart.
*/}}
{{- define "edgebot-umbrella.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create a default fully qualified app name.
We truncate at 63 chars because some Kubernetes name fields are limited to this (by the DNS naming spec).
If release name contains chart name it will be used as a full name.
*/}}
{{- define "edgebot-umbrella.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- $name := default .Chart.Name .Values.nameOverride }}
{{- if contains $name .Release.Name }}
{{- .Release.Name | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}
{{- end }}

{{/*
Create chart name and version as used by the chart label.
*/}}
{{- define "edgebot-umbrella.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Common labels
*/}}
{{- define "edgebot-umbrella.labels" -}}
helm.sh/chart: {{ include "edgebot-umbrella.chart" . }}
{{ include "edgebot-umbrella.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- with .Values.global.commonLabels }}
{{- toYaml . | nindent 0 }}
{{- end }}
{{- end }}

{{/*
Selector labels
*/}}
{{- define "edgebot-umbrella.selectorLabels" -}}
app.kubernetes.io/name: {{ include "edgebot-umbrella.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/*
Generate TimescaleDB connection DSN
*/}}
{{- define "edgebot-umbrella.timescaledb.dsn" -}}
{{- if .Values.timescaledb.enabled }}
{{- printf "postgresql://%s:%s@%s:5432/%s" 
    .Values.timescaledb.connection.user.name 
    .Values.timescaledb.connection.user.password
    (printf "%s-timescaledb" (include "edgebot-umbrella.fullname" .))
    .Values.timescaledb.connection.database }}
{{- else }}
{{- .Values.mothership.config.database.dsn }}
{{- end }}
{{- end }}

{{/*
Generate Loki URL
*/}}
{{- define "edgebot-umbrella.loki.url" -}}
{{- if .Values.observability.enabled }}
{{- printf "http://%s-observability-loki:3100" (include "edgebot-umbrella.fullname" .) }}
{{- else }}
{{- .Values.mothership.config.loki.url }}
{{- end }}
{{- end }}

{{/*
Apply development profile overrides
*/}}
{{- define "edgebot-umbrella.applyDevelopmentProfile" -}}
{{- if .Values.profiles.development.enabled }}
{{- $_ := mergeOverwrite .Values.mothership .Values.profiles.development.mothership }}
{{- $_ := mergeOverwrite .Values.observability .Values.profiles.development.observability }}
{{- if .Values.timescaledb.enabled }}
{{- $_ := mergeOverwrite .Values.timescaledb .Values.profiles.development.timescaledb }}
{{- end }}
{{- end }}
{{- end }}

{{/*
Apply production profile overrides
*/}}
{{- define "edgebot-umbrella.applyProductionProfile" -}}
{{- if .Values.profiles.production.enabled }}
{{- $_ := mergeOverwrite .Values.mothership .Values.profiles.production.mothership }}
{{- $_ := mergeOverwrite .Values.observability .Values.profiles.production.observability }}
{{- if .Values.timescaledb.enabled }}
{{- $_ := mergeOverwrite .Values.timescaledb .Values.profiles.production.timescaledb }}
{{- end }}
{{- end }}
{{- end }}