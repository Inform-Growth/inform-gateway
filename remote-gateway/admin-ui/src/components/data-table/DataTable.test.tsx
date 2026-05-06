import { describe, it, expect } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import type { ColumnDef } from '@tanstack/react-table';
import { DataTable } from './DataTable';

type Row = { id: string; name: string; calls: number };

const columns: ColumnDef<Row>[] = [
  { accessorKey: 'name', header: 'Name' },
  { accessorKey: 'calls', header: 'Calls' },
];

const data: Row[] = [
  { id: '1', name: 'Alice', calls: 10 },
  { id: '2', name: 'Bob',   calls: 3 },
];

describe('DataTable', () => {
  it('renders rows from data', () => {
    render(<DataTable columns={columns} data={data} getRowId={(r) => r.id} />);
    expect(screen.getByText('Alice')).toBeInTheDocument();
    expect(screen.getByText('Bob')).toBeInTheDocument();
  });

  it('renders empty state when no rows', () => {
    render(
      <DataTable columns={columns} data={[]} getRowId={(r) => r.id} emptyMessage="Nothing here" />
    );
    expect(screen.getByText('Nothing here')).toBeInTheDocument();
  });

  it('calls onRowClick with the row when a row is clicked', () => {
    let clicked: Row | null = null;
    render(
      <DataTable
        columns={columns}
        data={data}
        getRowId={(r) => r.id}
        onRowClick={(r) => { clicked = r; }}
      />,
    );
    fireEvent.click(screen.getByText('Alice'));
    expect(clicked).toEqual(data[0]);
  });

  it('highlights the selected row when selectedRowId is provided', () => {
    const { container } = render(
      <DataTable
        columns={columns}
        data={data}
        getRowId={(r) => r.id}
        selectedRowId="2"
      />,
    );
    const selected = container.querySelector('[data-selected="true"]');
    expect(selected?.textContent).toContain('Bob');
  });
});
