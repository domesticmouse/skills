<script setup lang="ts">
import AsciinemaPlayer from '../components/AsciinemaPlayer.vue'
</script>

<template>
  <div class="h-full w-full flex flex-col bg-[#121317] p-5 text-white overflow-hidden">
    <!-- Main Viewport Area -->
    <div class="flex-1 w-full min-h-0 flex items-center justify-center">
      <AsciinemaPlayer
        v-if="$frontmatter.cast || $frontmatter.castSrc"
        :src="$frontmatter.cast || $frontmatter.castSrc"
        :title="$frontmatter.title"
        :autoPlay="$frontmatter.autoPlay ?? false"
        :speed="$frontmatter.speed ?? 2.0"
        :maxSegmentDuration="$frontmatter.maxSegmentDuration ?? 30.0"
        :idleTimeLimit="$frontmatter.idleTimeLimit ?? 2.0"
        :fit="$frontmatter.fit ?? 'both'"
        :theme="$frontmatter.theme ?? 'dracula'"
        :markers="$frontmatter.markers ?? []"
        :pauseOnMarkers="$frontmatter.pauseOnMarkers ?? true"
        :showChapterBar="$frontmatter.showChapterBar ?? false"
        class="w-full h-full"
      />
      <div v-else class="w-full h-full flex flex-col justify-center">
        <slot />
      </div>
    </div>
  </div>
</template>
