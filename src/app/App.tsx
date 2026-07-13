import { Routes, Route, Navigate } from 'react-router-dom'
import { lazy, Suspense } from 'react'
import PhoneLayout from '@/shared/layouts/PhoneLayout'

const LoginPage = lazy(() => import('@/routes/login/LoginPage'))
const JoinRoomPage = lazy(() => import('@/routes/join/JoinRoomPage'))
const CreateRoomPage = lazy(() => import('@/routes/create/CreateRoomPage'))
const GameSelectionPage = lazy(() => import('@/routes/games/GameSelectionPage'))
const SystemSelectionPage = lazy(() => import('@/routes/games/trpg/SystemSelectionPage'))
const ScenarioSelectionPage = lazy(() => import('@/routes/games/trpg/ScenarioSelectionPage'))
const StoryPage = lazy(() => import('@/routes/games/trpg/StoryPage'))
const CharacterPage = lazy(() => import('@/routes/games/trpg/CharacterPage'))
const LobbyPage = lazy(() => import('@/routes/lobby/LobbyPage'))
const CharacterReadyPage = lazy(() => import('@/routes/character-ready/CharacterReadyPage'))
const RoomPage = lazy(() => import('@/routes/games/trpg/RoomPage'))

function LoadingFallback() {
  return (
    <div className="flex items-center justify-center min-h-[60vh] text-text-muted text-sm">
      加载中…
    </div>
  )
}

function App() {
  return (
    <PhoneLayout>
      <Suspense fallback={<LoadingFallback />}>
        <Routes>
          <Route path="/" element={<Navigate to="/login" replace />} />
          <Route path="/login" element={<LoginPage />} />
          <Route path="/join" element={<JoinRoomPage />} />
          <Route path="/create" element={<CreateRoomPage />} />
          <Route path="/games" element={<GameSelectionPage />} />
          <Route path="/games/:gameId" element={<SystemSelectionPage />} />
          <Route path="/games/:gameId/scenarios/:systemId" element={<ScenarioSelectionPage />} />
          <Route path="/story" element={<StoryPage />} />
          <Route path="/character" element={<CharacterPage />} />
          <Route path="/lobby" element={<LobbyPage />} />
          <Route path="/character-ready" element={<CharacterReadyPage />} />
          <Route path="/room" element={<RoomPage />} />
        </Routes>
      </Suspense>
    </PhoneLayout>
  )
}

export default App
