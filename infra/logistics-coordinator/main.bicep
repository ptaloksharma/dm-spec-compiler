// Bicep — isolated infrastructure for agent 'logistics-coordinator'.
// Deterministic; no secrets. Parameterize the connection at deploy time.
param location string = resourceGroup().location
param administratorLogin string
@secure()
param administratorPassword string

resource pg 'Microsoft.DBforPostgreSQL/flexibleServers@2023-03-01-preview' = {
  name: 'logistics-coordinator-db'
  location: location
  properties: {
    administratorLogin: administratorLogin
    administratorLoginPassword: administratorPassword
    version: '16'
  }
}

resource schema 'Microsoft.DBforPostgreSQL/flexibleServers/databases@2023-03-01-preview' = {
  parent: pg
  name: 'logistics_coordinator_schema'
}

output schemaName string = 'logistics_coordinator_schema'
output serverFqdn string = pg.properties.fullyQualifiedDomainName
