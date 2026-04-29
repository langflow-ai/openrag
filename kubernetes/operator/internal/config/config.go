package config

import (
	"os"
	"strings"
)

const (
	DefaultNamespace           = "openrag-control"
	metricsBindAddressEnv      = "METRICS_BIND_ADDRESS"
	healthProbeBindAddressEnv  = "HEALTH_PROBE_BIND_ADDRESS"
	leaderElectionNamespaceEnv = "LEADER_ELECTION_NAMESPACE"
	enableHTTP2Env             = "ENABLE_HTTP2"
	secureMetricsEnv           = "SECURE_METRICS"
	environment                = "Environment"
)

type OperatorConfig struct {
	HealthProbeBindAddress  string
	MetricsBindAddress      string
	LeaderElectionNamespace string
	LeaderElectionEnabled   bool
	EnableHTTP2             bool
	SecureMetrics           bool
	Environment             string
}

func NewOperatorConfig() OperatorConfig {
	return OperatorConfig{
		MetricsBindAddress:      getEnv(metricsBindAddressEnv, ":9090"),
		HealthProbeBindAddress:  getEnv(healthProbeBindAddressEnv, ":8080"),
		LeaderElectionNamespace: getEnv(leaderElectionNamespaceEnv, ""),
		LeaderElectionEnabled:   getEnv(leaderElectionNamespaceEnv, "") != "",
		EnableHTTP2:             strings.ToLower(getEnv(enableHTTP2Env, "false")) == "true",
		SecureMetrics:           strings.ToLower(getEnv(secureMetricsEnv, "false")) == "true",
		Environment:             getEnv(environment, "dev"),
	}
}

// getEnv reads an environment variable or returns a default value
func getEnv(key, defaultValue string) string {
	if value, exists := os.LookupEnv(key); exists {
		return value
	}
	return defaultValue
}
