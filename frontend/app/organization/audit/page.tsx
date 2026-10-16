"use client";

import { useEffect, useState } from "react";
import { MaterialIcon } from "@/components/shared/material-icon";
import { getOrganization } from "@/lib/api/organization";

interface AuditEvent {
  id: string;
  org_id: string;
  actor_user_id: string | null;
  project_id: string | null;
  event_type: string;
  action: string;
  target: string;
  metadata: Record<string, any>;
  created_at: string;
}

function formatTimestamp(isoStr: string): string {
  try {
    const d = new Date(isoStr);
    return isNaN(d.getTime()) ? isoStr : d.toISOString().replace("T", " ").slice(0, 19);
  } catch {
    return isoStr;
  }
}

export default function OrganizationAuditPage() {
  const [events, setEvents] = useState<AuditEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [actionFilter, setActionFilter] = useState("");
  const [page, setPage] = useState(0);
  const limit = 25;

  const org = getOrganization();

  const fetchAuditEvents = async () => {
    setLoading(true);
    setError(null);
    try {
      const params = new URLSearchParams();
      params.set("limit", String(limit));
      params.set("skip", String(page * limit));
      if (actionFilter.trim()) {
        params.set("action", actionFilter.trim());
      }

      const res = await fetch(`/api/v1/orgs/${org.id}/audit?${params.toString()}`);
      if (!res.ok) {
        if (res.status === 403) {
          throw new Error("You must be an organization admin to view the audit log.");
        }
        throw new Error(`Failed to load audit logs: ${res.statusText}`);
      }
      const data = await res.json();
      setEvents(data);
    } catch (err: any) {
      setError(err.message || "Failed to fetch audit log");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchAuditEvents();
  }, [page, actionFilter]);

  return (
    <div className="max-w-6xl mx-auto py-8 px-4 sm:px-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4 mb-8">
        <div>
          <div className="flex items-center gap-3">
            <div className="p-2 bg-emerald-500/10 rounded-lg text-emerald-400 flex items-center justify-center">
              <MaterialIcon name="shield" size={24} />
            </div>
            <div>
              <h1 className="text-2xl font-bold tracking-tight text-white">Security & Audit Log</h1>
              <p className="text-sm text-zinc-400">
                Immutable, SOC2-compliant activity trail for workspace {org.name}
              </p>
            </div>
          </div>
        </div>

        <button
          onClick={() => fetchAuditEvents()}
          className="flex items-center gap-2 px-3 py-2 bg-zinc-800 hover:bg-zinc-700 text-zinc-200 text-sm font-medium rounded-md border border-zinc-700 transition"
        >
          <MaterialIcon
            name="refresh"
            size={18}
            className={loading ? "animate-spin" : ""}
          />
          Refresh
        </button>
      </div>

      {/* Filters */}
      <div className="flex flex-wrap gap-4 mb-6 bg-zinc-900/60 p-4 rounded-lg border border-zinc-800">
        <div className="relative flex-1 min-w-[200px] flex items-center">
          <div className="absolute left-3 text-zinc-500 flex items-center">
            <MaterialIcon name="search" size={18} />
          </div>
          <input
            type="text"
            placeholder="Filter by action (e.g. create_project, invite_member)..."
            value={actionFilter}
            onChange={(e) => {
              setActionFilter(e.target.value);
              setPage(0);
            }}
            className="w-full bg-zinc-800/80 border border-zinc-700 rounded-md pl-9 pr-3 py-1.5 text-sm text-zinc-200 placeholder:text-zinc-500 focus:outline-none focus:ring-1 focus:ring-emerald-500"
          />
        </div>
      </div>

      {/* Content */}
      {error ? (
        <div className="p-4 bg-red-500/10 border border-red-500/20 rounded-lg text-red-400 text-sm">
          {error}
        </div>
      ) : loading && events.length === 0 ? (
        <div className="flex justify-center items-center py-24 text-zinc-500 gap-2">
          <MaterialIcon name="refresh" size={20} className="animate-spin" />
          Loading audit trail...
        </div>
      ) : events.length === 0 ? (
        <div className="text-center py-16 bg-zinc-900/30 border border-zinc-800/60 rounded-lg">
          <div className="flex justify-center mb-2 text-zinc-600">
            <MaterialIcon name="timeline" size={32} />
          </div>
          <h3 className="text-sm font-medium text-zinc-300">No audit events found</h3>
          <p className="text-xs text-zinc-500 mt-1">Mutating operations will appear here automatically.</p>
        </div>
      ) : (
        <div className="bg-zinc-900/70 border border-zinc-800 rounded-lg overflow-hidden shadow-xl">
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead className="bg-zinc-800/50 text-zinc-400 uppercase tracking-wider font-semibold border-b border-zinc-800">
                <tr>
                  <th className="py-3 px-4">Timestamp</th>
                  <th className="py-3 px-4">Event Type</th>
                  <th className="py-3 px-4">Action</th>
                  <th className="py-3 px-4">Target</th>
                  <th className="py-3 px-4">Actor</th>
                  <th className="py-3 px-4">Details</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-zinc-800/60">
                {events.map((ev) => (
                  <tr key={ev.id} className="hover:bg-zinc-800/30 transition">
                    <td className="py-3 px-4 font-mono text-zinc-400 whitespace-nowrap">
                      {ev.created_at ? formatTimestamp(ev.created_at) : "—"}
                    </td>
                    <td className="py-3 px-4">
                      <span className="inline-flex items-center px-2 py-0.5 rounded text-[11px] font-medium bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
                        {ev.event_type}
                      </span>
                    </td>
                    <td className="py-3 px-4 font-medium text-zinc-200">
                      {ev.action}
                    </td>
                    <td className="py-3 px-4 text-zinc-300 font-mono text-[11px] max-w-[200px] truncate" title={ev.target}>
                      {ev.target}
                    </td>
                    <td className="py-3 px-4 text-zinc-400 font-mono text-[11px]">
                      {ev.actor_user_id ? `${ev.actor_user_id.slice(0, 8)}...` : "System"}
                    </td>
                    <td className="py-3 px-4">
                      {ev.metadata && Object.keys(ev.metadata).length > 0 ? (
                        <pre className="text-[10px] bg-zinc-950 p-1.5 rounded text-zinc-400 max-w-[220px] overflow-x-auto border border-zinc-800">
                          {JSON.stringify(ev.metadata, null, 1)}
                        </pre>
                      ) : (
                        <span className="text-zinc-600">—</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {/* Pagination */}
          <div className="flex items-center justify-between px-4 py-3 bg-zinc-900 border-t border-zinc-800">
            <span className="text-xs text-zinc-400">
              Showing page {page + 1}
            </span>
            <div className="flex gap-2">
              <button
                disabled={page === 0}
                onClick={() => setPage((p) => Math.max(0, p - 1))}
                className="p-1 rounded bg-zinc-800 hover:bg-zinc-700 disabled:opacity-40 disabled:cursor-not-allowed text-zinc-300 flex items-center justify-center"
              >
                <MaterialIcon name="chevron_left" size={18} />
              </button>
              <button
                disabled={events.length < limit}
                onClick={() => setPage((p) => p + 1)}
                className="p-1 rounded bg-zinc-800 hover:bg-zinc-700 disabled:opacity-40 disabled:cursor-not-allowed text-zinc-300 flex items-center justify-center"
              >
                <MaterialIcon name="chevron_right" size={18} />
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
