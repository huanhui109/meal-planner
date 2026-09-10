import React from 'react'

interface PageHeaderProps {
  title: string
  subtitle?: string
  extra?: React.ReactNode
}

const PageHeader: React.FC<PageHeaderProps> = ({ title, subtitle, extra }) => (
  <div className="page-header">
    <div>
      <div className="page-header-title">{title}</div>
      {subtitle && <div className="page-header-sub">{subtitle}</div>}
    </div>
    {extra && <div className="page-header-extra">{extra}</div>}
  </div>
)

export default PageHeader
