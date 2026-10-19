import { useState } from "react";

const initialTasks = [
  { id: 1, text: "Reach out to David Leavitt re: Aaron", priority: 1, due: "Thu 4/10", done: false },
  { id: 2, text: "Make KSA and Utah versions of pitch decks", priority: 1, due: "This week", done: false },
  { id: 3, text: "Shepherd KU answer deck edit (Jeffery + Ed)", priority: 1, due: "This week", done: false },
  { id: 4, text: "Finish OpX redo for investment pitch", priority: 1, due: "ASAP", done: false },
  { id: 5, text: "Microphenomics next steps", priority: 2, due: "Ongoing", done: false },
  { id: 6, text: "Talk with Hassan about Archty timing", priority: 3, due: "TBD", done: false },
];

const initialPipeline = [
  "AI for foundational biology & drug discovery (collaboration forming with Thang, Keith, Stanford)",
  "Academic-commercial crossover via Computational Phenomics center",
];

const initialInbox = [];

const priorityColors = {
  1: { bg: "bg-red-50", border: "border-red-200", badge: "bg-red-100 text-red-800" },
  2: { bg: "bg-amber-50", border: "border-amber-200", badge: "bg-amber-100 text-amber-800" },
  3: { bg: "bg-blue-50", border: "border-blue-200", badge: "bg-blue-100 text-blue-800" },
};

const formatDate = () => {
  const d = new Date();
  const days = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];
  const months = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];
  return `${days[d.getDay()]}, ${months[d.getMonth()]} ${d.getDate()}, ${d.getFullYear()}`;
};

const daysUntil = (dateStr) => {
  if (!dateStr.match(/\d+\/\d+/)) return null;
  const [m, d] = dateStr.replace(/[^\d\/]/g, "").split("/").map(Number);
  const target = new Date(2026, m - 1, d);
  const now = new Date();
  now.setHours(0, 0, 0, 0);
  const diff = Math.ceil((target - now) / (1000 * 60 * 60 * 24));
  return diff;
};

export default function AnchorDashboard() {
  const [tasks, setTasks] = useState(initialTasks);
  const [inbox, setInbox] = useState(initialInbox);
  const [archive, setArchive] = useState([]);
  const [newTask, setNewTask] = useState("");
  const [newTaskPriority, setNewTaskPriority] = useState(1);
  const [newTaskDue, setNewTaskDue] = useState("");
  const [newInboxItem, setNewInboxItem] = useState("");
  const [showAddTask, setShowAddTask] = useState(false);
  const [showCapture, setShowCapture] = useState(false);
  const [showArchive, setShowArchive] = useState(false);
  const [activeTab, setActiveTab] = useState("dashboard");

  const activeTasks = tasks.filter((t) => !t.done);
  const urgentCount = activeTasks.filter((t) => t.priority === 1).length;

  const toggleDone = (id) => {
    const task = tasks.find((t) => t.id === id);
    if (task && !task.done) {
      setArchive((prev) => [
        { ...task, done: true, completedAt: new Date().toLocaleString() },
        ...prev,
      ]);
    }
    setTasks((prev) => prev.map((t) => (t.id === id ? { ...t, done: !t.done } : t)));
  };

  const addTask = () => {
    if (!newTask.trim()) return;
    const id = Math.max(...tasks.map((t) => t.id), 0) + 1;
    setTasks((prev) => [
      ...prev,
      { id, text: newTask.trim(), priority: newTaskPriority, due: newTaskDue || "TBD", done: false },
    ]);
    setNewTask("");
    setNewTaskDue("");
    setNewTaskPriority(1);
    setShowAddTask(false);
  };

  const captureInbox = () => {
    if (!newInboxItem.trim()) return;
    setInbox((prev) => [
      { id: Date.now(), text: newInboxItem.trim(), date: new Date().toLocaleDateString() },
      ...prev,
    ]);
    setNewInboxItem("");
    setShowCapture(false);
  };

  const promoteInbox = (item) => {
    const id = Math.max(...tasks.map((t) => t.id), 0) + 1;
    setTasks((prev) => [...prev, { id, text: item.text, priority: 2, due: "TBD", done: false }]);
    setInbox((prev) => prev.filter((i) => i.id !== item.id));
  };

  const removeInbox = (id) => {
    setInbox((prev) => prev.filter((i) => i.id !== id));
  };

  return (
    <div className="min-h-screen bg-gray-50 p-6" style={{ fontFamily: "system-ui, -apple-system, sans-serif" }}>
      <div className="max-w-3xl mx-auto">
        {/* Header */}
        <div className="mb-6">
          <div className="flex items-center justify-between mb-1">
            <h1 className="text-2xl font-bold text-gray-900">Anchor — Axmra</h1>
            <span className="text-sm text-gray-500">{formatDate()}</span>
          </div>
          <p className="text-sm text-gray-500">Commercial Dashboard</p>
        </div>

        {/* Stats Bar */}
        <div className="grid grid-cols-3 gap-3 mb-6">
          <div className="bg-white rounded-lg border border-gray-200 p-4 text-center">
            <div className="text-2xl font-bold text-gray-900">{activeTasks.length}</div>
            <div className="text-xs text-gray-500 mt-1">Active Tasks</div>
          </div>
          <div className="bg-white rounded-lg border border-red-200 p-4 text-center">
            <div className="text-2xl font-bold text-red-600">{urgentCount}</div>
            <div className="text-xs text-gray-500 mt-1">Urgent (P1)</div>
          </div>
          <div className="bg-white rounded-lg border border-gray-200 p-4 text-center">
            <div className="text-2xl font-bold text-green-600">{archive.length}</div>
            <div className="text-xs text-gray-500 mt-1">Completed</div>
          </div>
        </div>

        {/* Tabs */}
        <div className="flex gap-1 mb-4 bg-gray-100 rounded-lg p-1">
          {[
            { key: "dashboard", label: "Dashboard" },
            { key: "inbox", label: `Inbox${inbox.length ? ` (${inbox.length})` : ""}` },
            { key: "archive", label: "Archive" },
          ].map((tab) => (
            <button
              key={tab.key}
              onClick={() => setActiveTab(tab.key)}
              className={`flex-1 py-2 px-3 text-sm font-medium rounded-md transition-colors ${
                activeTab === tab.key
                  ? "bg-white text-gray-900 shadow-sm"
                  : "text-gray-500 hover:text-gray-700"
              }`}
            >
              {tab.label}
            </button>
          ))}
        </div>

        {/* Dashboard Tab */}
        {activeTab === "dashboard" && (
          <div>
            {/* Current Focus */}
            <div className="bg-amber-50 border border-amber-200 rounded-lg p-4 mb-4">
              <h2 className="text-sm font-semibold text-amber-800 mb-2">CURRENT FOCUS</h2>
              <ol className="space-y-1">
                <li className="text-sm text-amber-900">
                  <span className="font-semibold">1.</span> David Leavitt (Thu 4/10) — reach out re: Aaron
                </li>
                <li className="text-sm text-amber-900">
                  <span className="font-semibold">2.</span> KSA + Utah pitch decks — regional versions
                </li>
                <li className="text-sm text-amber-900">
                  <span className="font-semibold">3.</span> KU answer deck — shepherd Jeffery & Ed's edit
                </li>
              </ol>
            </div>

            {/* Active Priorities */}
            <div className="bg-white border border-gray-200 rounded-lg mb-4">
              <div className="flex items-center justify-between p-4 border-b border-gray-100">
                <h2 className="text-sm font-semibold text-gray-700">ACTIVE PRIORITIES</h2>
                <button
                  onClick={() => setShowAddTask(!showAddTask)}
                  className="text-xs font-medium text-blue-600 hover:text-blue-800 bg-blue-50 px-3 py-1.5 rounded-md hover:bg-blue-100 transition-colors"
                >
                  + Add Task
                </button>
              </div>

              {showAddTask && (
                <div className="p-4 bg-blue-50 border-b border-blue-100">
                  <input
                    type="text"
                    placeholder="Task description..."
                    value={newTask}
                    onChange={(e) => setNewTask(e.target.value)}
                    onKeyDown={(e) => e.key === "Enter" && addTask()}
                    className="w-full px-3 py-2 text-sm border border-gray-300 rounded-md mb-2 focus:outline-none focus:ring-2 focus:ring-blue-300"
                  />
                  <div className="flex gap-2 items-center">
                    <select
                      value={newTaskPriority}
                      onChange={(e) => setNewTaskPriority(Number(e.target.value))}
                      className="text-sm border border-gray-300 rounded-md px-2 py-1.5 focus:outline-none focus:ring-2 focus:ring-blue-300"
                    >
                      <option value={1}>Priority 1</option>
                      <option value={2}>Priority 2</option>
                      <option value={3}>Priority 3</option>
                    </select>
                    <input
                      type="text"
                      placeholder="Due (e.g. This week, 4/15)"
                      value={newTaskDue}
                      onChange={(e) => setNewTaskDue(e.target.value)}
                      className="flex-1 px-3 py-1.5 text-sm border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-300"
                    />
                    <button
                      onClick={addTask}
                      className="bg-blue-600 text-white text-sm px-4 py-1.5 rounded-md hover:bg-blue-700 transition-colors"
                    >
                      Add
                    </button>
                  </div>
                </div>
              )}

              <div className="divide-y divide-gray-50">
                {activeTasks
                  .sort((a, b) => a.priority - b.priority)
                  .map((task) => {
                    const days = daysUntil(task.due);
                    const colors = priorityColors[task.priority] || priorityColors[3];
                    return (
                      <div
                        key={task.id}
                        className={`flex items-center gap-3 p-4 hover:bg-gray-50 transition-colors ${
                          task.priority === 1 ? "border-l-4 border-l-red-400" : ""
                        }`}
                      >
                        <button
                          onClick={() => toggleDone(task.id)}
                          className="w-5 h-5 rounded border-2 border-gray-300 hover:border-green-500 hover:bg-green-50 flex-shrink-0 transition-colors flex items-center justify-center"
                          title="Mark done"
                        >
                        </button>
                        <div className="flex-1 min-w-0">
                          <div className="text-sm text-gray-900">{task.text}</div>
                          <div className="flex items-center gap-2 mt-1">
                            <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${colors.badge}`}>
                              P{task.priority}
                            </span>
                            <span className={`text-xs text-gray-500 ${days !== null && days <= 3 ? "text-red-600 font-medium" : ""}`}>
                              {task.due}
                              {days !== null && days >= 0 && ` (${days}d)`}
                            </span>
                          </div>
                        </div>
                      </div>
                    );
                  })}
              </div>
            </div>

            {/* Pipeline */}
            <div className="bg-white border border-gray-200 rounded-lg p-4">
              <h2 className="text-sm font-semibold text-gray-700 mb-2">PIPELINE</h2>
              {initialPipeline.map((item, i) => (
                <div key={i} className="text-sm text-gray-600 py-1 flex items-start gap-2">
                  <span className="text-gray-400 mt-0.5">&#8594;</span>
                  <span>{item}</span>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Inbox Tab */}
        {activeTab === "inbox" && (
          <div>
            <div className="bg-white border border-gray-200 rounded-lg">
              <div className="flex items-center justify-between p-4 border-b border-gray-100">
                <h2 className="text-sm font-semibold text-gray-700">INBOX</h2>
                <button
                  onClick={() => setShowCapture(!showCapture)}
                  className="text-xs font-medium text-blue-600 hover:text-blue-800 bg-blue-50 px-3 py-1.5 rounded-md hover:bg-blue-100 transition-colors"
                >
                  + Capture
                </button>
              </div>

              {showCapture && (
                <div className="p-4 bg-blue-50 border-b border-blue-100">
                  <div className="flex gap-2">
                    <input
                      type="text"
                      placeholder="Quick capture — idea, task, note..."
                      value={newInboxItem}
                      onChange={(e) => setNewInboxItem(e.target.value)}
                      onKeyDown={(e) => e.key === "Enter" && captureInbox()}
                      className="flex-1 px-3 py-2 text-sm border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-300"
                    />
                    <button
                      onClick={captureInbox}
                      className="bg-blue-600 text-white text-sm px-4 py-2 rounded-md hover:bg-blue-700 transition-colors"
                    >
                      Save
                    </button>
                  </div>
                </div>
              )}

              {inbox.length === 0 ? (
                <div className="p-8 text-center text-sm text-gray-400">
                  Inbox is empty. Use "Capture" to quick-add ideas and tasks.
                </div>
              ) : (
                <div className="divide-y divide-gray-50">
                  {inbox.map((item) => (
                    <div key={item.id} className="flex items-center justify-between p-4 hover:bg-gray-50">
                      <div>
                        <div className="text-sm text-gray-900">{item.text}</div>
                        <div className="text-xs text-gray-400 mt-0.5">{item.date}</div>
                      </div>
                      <div className="flex gap-1">
                        <button
                          onClick={() => promoteInbox(item)}
                          className="text-xs text-green-600 hover:text-green-800 bg-green-50 px-2 py-1 rounded hover:bg-green-100 transition-colors"
                          title="Promote to task"
                        >
                          Promote
                        </button>
                        <button
                          onClick={() => removeInbox(item.id)}
                          className="text-xs text-gray-400 hover:text-red-600 px-2 py-1 rounded hover:bg-red-50 transition-colors"
                          title="Dismiss"
                        >
                          Dismiss
                        </button>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        )}

        {/* Archive Tab */}
        {activeTab === "archive" && (
          <div>
            <div className="bg-white border border-gray-200 rounded-lg">
              <div className="p-4 border-b border-gray-100">
                <h2 className="text-sm font-semibold text-gray-700">COMPLETED</h2>
              </div>
              {archive.length === 0 ? (
                <div className="p-8 text-center text-sm text-gray-400">
                  No completed tasks yet. Check off items from the dashboard to see them here.
                </div>
              ) : (
                <div className="divide-y divide-gray-50">
                  {archive.map((task) => (
                    <div key={task.id} className="p-4">
                      <div className="text-sm text-gray-500 line-through">{task.text}</div>
                      <div className="text-xs text-gray-400 mt-1">Completed {task.completedAt}</div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
