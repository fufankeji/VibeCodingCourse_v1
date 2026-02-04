import { useEffect, useRef } from 'react'

interface Particle {
  x: number
  y: number
  vx: number
  vy: number
  size: number
  color: string
  alpha: number
  targetAlpha: number
}

export function ParticleBackground() {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const particlesRef = useRef<Particle[]>([])
  const mouseRef = useRef({ x: 0, y: 0 })
  const animationRef = useRef<number>(0)

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return

    const ctx = canvas.getContext('2d')
    if (!ctx) return

    // Warm color palette
    const colors = [
      '#f97316', // orange
      '#f59e0b', // amber
      '#eab308', // yellow
      '#ef4444', // red
      '#fb923c', // light orange
      '#fbbf24', // light amber
    ]

    const resize = () => {
      canvas.width = window.innerWidth
      canvas.height = window.innerHeight
      initParticles()
    }

    const initParticles = () => {
      const particleCount = Math.floor((canvas.width * canvas.height) / 15000)
      particlesRef.current = []

      for (let i = 0; i < particleCount; i++) {
        particlesRef.current.push({
          x: Math.random() * canvas.width,
          y: Math.random() * canvas.height,
          vx: (Math.random() - 0.5) * 0.3,
          vy: (Math.random() - 0.5) * 0.3,
          size: Math.random() * 2 + 1,
          color: colors[Math.floor(Math.random() * colors.length)],
          alpha: Math.random() * 0.5 + 0.1,
          targetAlpha: Math.random() * 0.5 + 0.1,
        })
      }
    }

    const drawParticle = (p: Particle) => {
      ctx.beginPath()
      ctx.arc(p.x, p.y, p.size, 0, Math.PI * 2)
      ctx.fillStyle = p.color
      ctx.globalAlpha = p.alpha
      ctx.fill()
      ctx.globalAlpha = 1
    }

    const drawConnections = () => {
      const particles = particlesRef.current
      const maxDistance = 120

      for (let i = 0; i < particles.length; i++) {
        for (let j = i + 1; j < particles.length; j++) {
          const dx = particles[i].x - particles[j].x
          const dy = particles[i].y - particles[j].y
          const distance = Math.sqrt(dx * dx + dy * dy)

          if (distance < maxDistance) {
            const opacity = (1 - distance / maxDistance) * 0.15
            ctx.beginPath()
            ctx.moveTo(particles[i].x, particles[i].y)
            ctx.lineTo(particles[j].x, particles[j].y)
            
            const gradient = ctx.createLinearGradient(
              particles[i].x, particles[i].y,
              particles[j].x, particles[j].y
            )
            gradient.addColorStop(0, particles[i].color)
            gradient.addColorStop(1, particles[j].color)
            
            ctx.strokeStyle = gradient
            ctx.globalAlpha = opacity
            ctx.lineWidth = 0.5
            ctx.stroke()
            ctx.globalAlpha = 1
          }
        }
      }

      // Draw connections to mouse
      const mouse = mouseRef.current
      for (const p of particles) {
        const dx = p.x - mouse.x
        const dy = p.y - mouse.y
        const distance = Math.sqrt(dx * dx + dy * dy)

        if (distance < 200) {
          const opacity = (1 - distance / 200) * 0.3
          ctx.beginPath()
          ctx.moveTo(p.x, p.y)
          ctx.lineTo(mouse.x, mouse.y)
          ctx.strokeStyle = p.color
          ctx.globalAlpha = opacity
          ctx.lineWidth = 1
          ctx.stroke()
          ctx.globalAlpha = 1
        }
      }
    }

    const updateParticles = () => {
      const particles = particlesRef.current

      for (const p of particles) {
        // Update position
        p.x += p.vx
        p.y += p.vy

        // Bounce off edges
        if (p.x < 0 || p.x > canvas.width) p.vx *= -1
        if (p.y < 0 || p.y > canvas.height) p.vy *= -1

        // Smooth alpha transition
        if (Math.random() < 0.01) {
          p.targetAlpha = Math.random() * 0.5 + 0.1
        }
        p.alpha += (p.targetAlpha - p.alpha) * 0.02

        // Mouse interaction
        const mouse = mouseRef.current
        const dx = p.x - mouse.x
        const dy = p.y - mouse.y
        const distance = Math.sqrt(dx * dx + dy * dy)

        if (distance < 150) {
          const force = (150 - distance) / 150
          p.vx += (dx / distance) * force * 0.02
          p.vy += (dy / distance) * force * 0.02
        }

        // Speed limit
        const speed = Math.sqrt(p.vx * p.vx + p.vy * p.vy)
        if (speed > 1) {
          p.vx = (p.vx / speed) * 1
          p.vy = (p.vy / speed) * 1
        }
      }
    }

    const animate = () => {
      ctx.clearRect(0, 0, canvas.width, canvas.height)

      updateParticles()
      drawConnections()
      
      for (const p of particlesRef.current) {
        drawParticle(p)
      }

      animationRef.current = requestAnimationFrame(animate)
    }

    const handleMouseMove = (e: MouseEvent) => {
      mouseRef.current = { x: e.clientX, y: e.clientY }
    }

    window.addEventListener('resize', resize)
    window.addEventListener('mousemove', handleMouseMove)
    
    resize()
    animate()

    return () => {
      window.removeEventListener('resize', resize)
      window.removeEventListener('mousemove', handleMouseMove)
      cancelAnimationFrame(animationRef.current)
    }
  }, [])

  return (
    <canvas
      ref={canvasRef}
      className="fixed inset-0 pointer-events-none z-0"
      style={{ opacity: 0.6 }}
    />
  )
}
