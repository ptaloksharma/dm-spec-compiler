// Bicep — isolated infrastructure for agent 'customs-agent'.
// Deterministic; no secrets. Parameterize the connection at deploy time.
param location string = resourceGroup().location
param administratorLogin string
@secure()
param administratorPassword string

resource pg 'Microsoft.DBforPostgreSQL/flexibleServers@2023-03-01-preview' = {
  name: 'customs-agent-db'
  location: location
  properties: {
    administratorLogin: administratorLogin
    administratorLoginPassword: administratorPassword
    version: '16'
  }
}

resource schema 'Microsoft.DBforPostgreSQL/flexibleServers/databases@2023-03-01-preview' = {
  parent: pg
  name: 'customs_schema'
}

output schemaName string = 'customs_schema'
output serverFqdn string = pg.properties.fullyQualifiedDomainName
