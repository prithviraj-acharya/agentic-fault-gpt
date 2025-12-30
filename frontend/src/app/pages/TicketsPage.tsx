import { useState } from 'react';
import { Link } from 'react-router-dom';
import { ConfidenceBar, StatusBadge } from '../components/TicketTableWidgets';
import { ArrowRightIcon } from '@heroicons/react/20/solid';

const TICKETS = [
  {
    id: 'TCK-001',
    fault: 'SAT_NOT_DROPPING_WHEN_VALVE_HIGH',
    location: 'AHU 1',
    confidence: 92,
    created: '2025-12-30 17:25',
    status: 'Pending',
    faultType: 'Cooling',
  },
  {
    id: 'TCK-002',
    fault: 'ZONE_TEMP_DRIFT',
    location: 'Zone 3',
    confidence: 78,
    created: '2025-12-29 14:10',
    status: 'Approved',
    faultType: 'Zone',
  },
  {
    id: 'TCK-003',
    fault: 'STUCK_DAMPER',
    location: 'AHU 2',
    confidence: 63,
    created: '2025-12-28 09:45',
    status: 'Rejected',
    faultType: 'Damper',
  },
];

const STATUS_OPTIONS = ['All Status', 'Open', 'Closed', 'In Progress'];
const FAULT_TYPE_OPTIONS = ['All Fault Types', 'Cooling', 'Zone', 'Damper'];

import { MagnifyingGlassIcon, FunnelIcon } from '@heroicons/react/24/solid';

export function TicketsPage() {
  const [search, setSearch] = useState('');
  const [status, setStatus] = useState('All Status');
  const [faultType, setFaultType] = useState('All Fault Types');

  const filtered = TICKETS.filter((t) => {
    const matchesSearch =
      t.id.toLowerCase().includes(search.toLowerCase()) ||
      t.fault.toLowerCase().includes(search.toLowerCase()) ||
      t.location.toLowerCase().includes(search.toLowerCase());
    const matchesStatus = status === 'All Status' || t.status === status;
    const matchesFaultType = faultType === 'All Fault Types' || t.faultType === faultType;
    return matchesSearch && matchesStatus && matchesFaultType;
  });

  return (
    <div className="space-y-6 px-6">
      <div className="bg-red-50 border border-red-200 text-red-800 rounded px-4 py-2 text-sm mb-2">
        <strong>Demo:</strong> This page is currently static and displays dummy data only.
      </div>
      {/* Header Title Bar */}
      <div className="flex items-center justify-between pt-6 pb-2">
        <div className="text-2xl font-semibold text-slate-900">Ticket Management</div>
      </div>

      {/* Summary Cards Row */}
      <div className="flex gap-6">
        <div className="flex-1 rounded-lg bg-white shadow-sm border border-slate-200 p-5 flex flex-col items-start">
          <div className="text-xs uppercase tracking-wide text-slate-500 mb-1">Awaiting Review</div>
          <div className="text-3xl font-bold text-slate-900">2</div>
        </div>
        <div className="flex-1 rounded-lg bg-white shadow-sm border border-slate-200 p-5 flex flex-col items-start">
          <div className="text-xs uppercase tracking-wide text-slate-500 mb-1">High Confidence Tickets</div>
          <div className="text-3xl font-bold text-slate-900">2</div>
        </div>
      </div>

      {/* Filter & Search Bar */}
      <div className="flex flex-wrap items-center justify-between gap-4 pt-4 pb-2">
        {/* Search input with icon */}
        <div className="relative flex-1 max-w-xs">
          <span className="absolute inset-y-0 left-0 flex items-center pl-3 pointer-events-none">
            <MagnifyingGlassIcon className="w-5 h-5 text-slate-400" />
          </span>
          <input
            type="text"
            placeholder="Search tickets..."
            className="w-full border border-slate-200 rounded pl-10 pr-3 py-2 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-purple-200"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>
        {/* Filter dropdowns with icon */}
        <div className="flex gap-2">
          <div className="relative">
            <FunnelIcon className="w-4 h-4 text-slate-400 absolute left-2 top-1/2 -translate-y-1/2 pointer-events-none" />
            <select
              className="appearance-none border border-slate-200 rounded pl-8 pr-6 py-2 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-purple-200"
              value={status}
              onChange={(e) => setStatus(e.target.value)}
            >
              {STATUS_OPTIONS.map((s) => (
                <option key={s} value={s}>{s}</option>
              ))}
            </select>
          </div>
          <div className="relative">
            <FunnelIcon className="w-4 h-4 text-slate-400 absolute left-2 top-1/2 -translate-y-1/2 pointer-events-none" />
            <select
              className="appearance-none border border-slate-200 rounded pl-8 pr-6 py-2 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-purple-200"
              value={faultType}
              onChange={(e) => setFaultType(e.target.value)}
            >
              {FAULT_TYPE_OPTIONS.map((f) => (
                <option key={f} value={f}>{f}</option>
              ))}
            </select>
          </div>
        </div>
      </div>

      {/* Ticket List Table (unchanged) */}
      <div className="overflow-x-auto">
        <table className="min-w-full table-fixed border border-slate-200 rounded bg-white">
          <colgroup>
            <col style={{ width: '120px' }} />
            <col style={{ width: '260px' }} />
            <col style={{ width: '140px' }} />
            <col style={{ width: '160px' }} />
            <col style={{ width: '120px' }} />
            <col style={{ width: '40px' }} />
          </colgroup>
          <thead>
            <tr className="bg-slate-50 text-slate-500 text-xs uppercase">
              <th className="px-4 py-2 border-b font-semibold text-left align-middle">Ticket ID</th>
              <th className="px-4 py-2 border-b font-semibold text-left align-middle">Fault Name + Location</th>
              <th className="px-4 py-2 border-b font-semibold text-left align-middle">Confidence</th>
              <th className="px-4 py-2 border-b font-semibold text-left align-middle">Created</th>
              <th className="px-4 py-2 border-b font-semibold text-left align-middle">Status</th>
              <th className="px-2 py-2 border-b font-semibold text-left align-middle"></th>
            </tr>
          </thead>
          <tbody>
            {filtered.length === 0 ? (
              <tr>
                <td colSpan={6} className="text-center text-slate-500 py-6">No tickets found.</td>
              </tr>
            ) : (
              filtered.map((t) => {
                let confidenceNum = Number(t.confidence);
                if (isNaN(confidenceNum)) confidenceNum = 0;
                return (
                  <tr
                    key={t.id}
                    className="border-b last:border-b-0 hover:bg-slate-50 transition cursor-pointer group"
                    onClick={() => window.location.href = `/tickets/${t.id}`}
                  >
                    <td className="px-4 py-2 font-mono text-sm align-middle">
                      <Link to={`/tickets/${t.id}`} className="text-purple-700 hover:underline">{t.id}</Link>
                    </td>
                    <td className="px-4 py-2 text-sm align-middle">
                      <div className="font-medium text-slate-900 leading-tight">{t.fault}</div>
                      <div className="text-xs text-slate-500 leading-tight">{t.location}</div>
                    </td>
                    <td className="px-4 py-2 align-middle">
                      <ConfidenceBar value={confidenceNum} />
                    </td>
                    <td className="px-4 py-2 text-sm align-middle">{t.created}</td>
                    <td className="px-4 py-2 align-middle">
                      <StatusBadge status={t.status} />
                    </td>
                    <td className="px-2 py-2 align-middle text-right">
                      <ArrowRightIcon className="w-5 h-5 text-slate-400 group-hover:text-purple-600 inline-block align-middle" />
                    </td>
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
