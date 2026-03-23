{{/*
Expand the chart name.
*/}}
{{- define "pf9mngt.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create a default fully qualified app name.
Truncated at 63 chars following DNS constraints.
*/}}
{{- define "pf9mngt.fullname" -}}
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
Chart label for tracking which chart installed this resource.
*/}}
{{- define "pf9mngt.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Common labels applied to every resource.
*/}}
{{- define "pf9mngt.labels" -}}
helm.sh/chart: {{ include "pf9mngt.chart" . }}
{{ include "pf9mngt.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{/*
Selector labels (used in matchLabels and podLabels).
*/}}
{{- define "pf9mngt.selectorLabels" -}}
app.kubernetes.io/name: {{ include "pf9mngt.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/*
Target namespace — honours .Values.namespace.name when set.
*/}}
{{- define "pf9mngt.namespace" -}}
{{- if .Values.namespace.name -}}
{{ .Values.namespace.name }}
{{- else -}}
{{ .Release.Namespace }}
{{- end }}
{{- end }}

{{/*
Resolve an application image tag.
Usage: include "pf9mngt.imageTag" (dict "svcTag" .Values.api.image.tag "global" .Values.global)
Returns the per-service tag when non-empty, otherwise falls back to global.imageTag.
*/}}
{{- define "pf9mngt.imageTag" -}}
{{- if .svcTag -}}
{{ .svcTag }}
{{- else -}}
{{ .global.imageTag }}
{{- end }}
{{- end }}

{{/*
Build a full image reference for application services (built in this repo).
Usage: include "pf9mngt.appImage" (dict "repo" .Values.api.image.repository "svcTag" .Values.api.image.tag "global" .Values.global)
*/}}
{{- define "pf9mngt.appImage" -}}
{{ .global.imageRepo }}/{{ .repo }}:{{ include "pf9mngt.imageTag" (dict "svcTag" .svcTag "global" .global) }}
{{- end }}
